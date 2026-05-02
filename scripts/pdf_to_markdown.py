#!/usr/bin/env python3
"""Convert a PDF to Markdown through a configurable layout-parsing API.

The API token is read from an environment variable. Do not hardcode tokens in
this file, shell history, docs, or wiki pages.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import requests

from wiki_common import write_text


DEFAULT_API_URL = "https://q6mbb0r0t8m9q4pf.aistudio-app.com/layout-parsing"
DEFAULT_TOKEN_ENV = "OPEN_LLM_WIKI_LAYOUT_TOKEN"
FALLBACK_TOKEN_ENV = "AI_STUDIO_LAYOUT_TOKEN"
DEFAULT_IGNORE_LABELS = [
    "header",
    "header_image",
    "footer",
    "footer_image",
    "number",
    "footnote",
    "aside_text",
]
DEFAULT_OPTIONS = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useLayoutDetection": True,
    "useChartRecognition": False,
    "useSealRecognition": True,
    "useOcrForImageBlock": False,
    "mergeTables": True,
    "relevelTitles": True,
    "layoutShapeMode": "auto",
    "promptLabel": "ocr",
    "repetitionPenalty": 1,
    "temperature": 0,
    "topP": 1,
    "minPixels": 147384,
    "maxPixels": 2822400,
    "layoutNms": True,
    "restructurePages": True,
}


def read_token(token_env: str) -> str:
    token = os.environ.get(token_env) or os.environ.get(FALLBACK_TOKEN_ENV)
    if not token:
        raise SystemExit(
            f"Missing API token. Set {token_env}=<token>"
            + (f" or {FALLBACK_TOKEN_ENV}=<token>." if token_env != FALLBACK_TOKEN_ENV else ".")
        )
    return token


def safe_output_path(output_dir: Path, remote_name: str) -> Path:
    clean = remote_name.replace("\\", "/").lstrip("/")
    parts = [part for part in clean.split("/") if part and part not in {".", ".."}]
    if not parts:
        raise ValueError(f"unsafe image path from API: {remote_name!r}")
    path = output_dir.joinpath(*parts).resolve()
    try:
        path.relative_to(output_dir.resolve())
    except ValueError:
        raise ValueError(f"image path escapes output directory: {remote_name!r}")
    return path


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported image URL scheme: {url}")


def build_payload(file_path: Path, file_type: int, options_file: Path | None) -> dict[str, object]:
    file_bytes = file_path.read_bytes()
    file_data = base64.b64encode(file_bytes).decode("ascii")
    payload: dict[str, object] = {
        "file": file_data,
        "fileType": file_type,
        "markdownIgnoreLabels": DEFAULT_IGNORE_LABELS,
        **DEFAULT_OPTIONS,
    }
    if options_file:
        overrides = json.loads(options_file.read_text(encoding="utf-8"))
        if not isinstance(overrides, dict):
            raise SystemExit("--options-file must contain a JSON object")
        payload.update(overrides)
    return payload


def download_file(url: str, target: Path, timeout: int) -> None:
    validate_url(url)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.content)


def convert(args: argparse.Namespace) -> int:
    input_path = args.input.resolve()
    if not input_path.exists():
        raise SystemExit(f"input file not found: {input_path}")
    if input_path.suffix.lower() != ".pdf" and args.file_type == 0:
        raise SystemExit("file type 0 expects a PDF input")
    size = input_path.stat().st_size
    if size > args.max_bytes:
        raise SystemExit(f"input is {size} bytes, above --max-bytes {args.max_bytes}")

    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = build_payload(input_path, args.file_type, args.options_file)
    if args.dry_run:
        print(f"input: {input_path}")
        print(f"output: {output_dir}")
        print(f"api_url: {args.api_url}")
        print(f"file_type: {args.file_type}")
        print(f"payload_keys: {sorted(payload.keys())}")
        print("dry run: no API request sent")
        return 0

    token = read_token(args.token_env)
    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/json",
    }
    response = requests.post(args.api_url, json=payload, headers=headers, timeout=args.timeout)
    response.raise_for_status()
    data = response.json()
    if "result" not in data or "layoutParsingResults" not in data["result"]:
        raise SystemExit("API response did not contain result.layoutParsingResults")

    result = data["result"]
    markdown_paths: list[str] = []
    combined_parts: list[str] = []
    for index, item in enumerate(result["layoutParsingResults"]):
        markdown = item.get("markdown", {})
        markdown_text = markdown.get("text", "")
        md_path = output_dir / f"doc_{index}.md"
        write_text(md_path, markdown_text)
        markdown_paths.append(str(md_path))
        combined_parts.append(markdown_text.rstrip())

        if args.download_images:
            for image_path, image_url in markdown.get("images", {}).items():
                target = safe_output_path(output_dir, image_path)
                download_file(image_url, target, args.timeout)
            for image_name, image_url in item.get("outputImages", {}).items():
                target = safe_output_path(output_dir, f"output_images/{image_name}_{index}.jpg")
                download_file(image_url, target, args.timeout)

    combined = output_dir / args.combined_name
    write_text(combined, "\n\n---\n\n".join(part for part in combined_parts if part))

    manifest = {
        "input": str(input_path),
        "api_url": args.api_url,
        "file_type": args.file_type,
        "documents": markdown_paths,
        "combined": str(combined),
        "download_images": args.download_images,
    }
    write_text(output_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    print(f"combined markdown: {combined}")
    print(f"manifest: {output_dir / 'manifest.json'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a PDF to Markdown using a layout-parsing API.")
    parser.add_argument("input", type=Path, help="Local PDF path.")
    parser.add_argument("--output", type=Path, default=Path("output"), help="Output directory.")
    parser.add_argument("--api-url", default=os.environ.get("OPEN_LLM_WIKI_LAYOUT_API_URL", DEFAULT_API_URL))
    parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    parser.add_argument("--file-type", type=int, choices=[0, 1], default=0, help="0=PDF, 1=image.")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-bytes", type=int, default=50 * 1024 * 1024)
    parser.add_argument("--options-file", type=Path, help="JSON object overriding API options.")
    parser.add_argument("--combined-name", default="combined.md")
    parser.add_argument("--no-download-images", dest="download_images", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    parser.set_defaults(download_images=True)
    return convert(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
