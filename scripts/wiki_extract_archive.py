#!/usr/bin/env python3
"""Safely extract a local ZIP corpus archive into a vault raw folder."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from wiki_common import ensure_within, rel


CHUNK_SIZE = 1024 * 1024
MANIFEST_PATH = Path("_state") / "archive-extract-manifest.jsonl"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == stat.S_IFLNK


def normalize_member_name(info: zipfile.ZipInfo) -> PurePosixPath | None:
    raw_name = info.filename.replace("\\", "/")
    if info.is_dir() or raw_name.endswith("/"):
        return None
    if not raw_name:
        raise SystemExit("archive member path is empty")

    parts = raw_name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SystemExit(f"archive member path is unsafe: {info.filename}")
    if raw_name.startswith("/"):
        raise SystemExit(f"archive member path is absolute: {info.filename}")
    if ":" in parts[0]:
        raise SystemExit(f"archive member path uses a drive prefix: {info.filename}")
    if zip_member_is_symlink(info):
        raise SystemExit(f"archive member is a symlink and cannot be extracted: {info.filename}")

    return PurePosixPath(*parts)


def is_packaging_junk(member: PurePosixPath) -> bool:
    return member.parts[0] == "__MACOSX" or member.name == ".DS_Store"


def resolve_vault_child(vault: Path, value: Path) -> Path:
    return value if value.is_absolute() else vault / value


def collect_plan(vault: Path, archive: Path, output_dir: Path) -> tuple[list[dict[str, object]], list[str]]:
    planned: list[dict[str, object]] = []
    skipped: list[str] = []
    seen_targets: set[str] = set()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            member = normalize_member_name(info)
            if member is None:
                continue
            if is_packaging_junk(member):
                skipped.append(info.filename)
                continue
            target = ensure_within(
                output_dir / Path(member.as_posix()),
                output_dir,
                "archive member must stay inside the output directory",
            )
            if target.exists():
                raise SystemExit(f"archive extraction would overwrite an existing file: {rel(target, vault)}")
            target_rel = rel(target, output_dir)
            if target_rel in seen_targets:
                raise SystemExit(f"archive contains duplicate output path: {target_rel}")
            seen_targets.add(target_rel)
            planned.append(
                {
                    "member": info.filename,
                    "target": target,
                    "size_bytes": info.file_size,
                }
            )
    return planned, skipped


def extract_plan(
    vault: Path,
    archive: Path,
    output_dir: Path,
    planned: list[dict[str, object]],
    skipped: list[str],
) -> Path:
    records: list[dict[str, object]] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for item in planned:
            info = zf.getinfo(str(item["member"]))
            target = Path(item["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with zf.open(info) as src, target.open("xb") as dst:
                for chunk in iter(lambda: src.read(CHUNK_SIZE), b""):
                    dst.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            records.append(
                {
                    "path": rel(target, vault),
                    "size_bytes": size,
                    "sha256": digest.hexdigest(),
                }
            )

    manifest = ensure_within(vault / MANIFEST_PATH, vault / "_state", "archive manifest must stay inside _state")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "event": "archive_extract",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "archive_path": rel(archive, vault),
        "archive_sha256": sha256_file(archive),
        "output_dir": rel(output_dir, vault),
        "file_count": len(records),
        "files": records,
        "skipped_entries": skipped,
    }
    with manifest.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely extract a ZIP corpus archive that already lives under vault/raw/.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Safety behavior:\n"
            "  - archive path must be inside <vault>/raw/\n"
            "  - output directory must be a subdirectory of <vault>/raw/\n"
            "  - absolute paths, '..', drive prefixes, symlinks, and overwrites are rejected\n"
            "  - __MACOSX/ and .DS_Store packaging entries are skipped\n"
            "  - extraction appends _state/archive-extract-manifest.jsonl\n"
            "\n"
            "Example:\n"
            "  python scripts/wiki_extract_archive.py my-vault raw/inbox/deepseek.zip --dry-run\n"
            "  python scripts/wiki_extract_archive.py my-vault raw/inbox/deepseek.zip --output-dir raw/deepseek_paper\n"
        ),
    )
    parser.add_argument("vault", type=Path, help="Vault root.")
    parser.add_argument("archive", type=Path, help="ZIP archive path under vault/raw/.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Destination directory under vault/raw/. Defaults to raw/<archive-stem>.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the extraction plan without writing files.")
    args = parser.parse_args()

    vault = args.vault.resolve()
    raw_dir = ensure_within(vault / "raw", vault, "raw directory must stay inside the vault")
    archive = ensure_within(resolve_vault_child(vault, args.archive), raw_dir, "archive must stay inside vault/raw")
    if archive.suffix.lower() != ".zip":
        raise SystemExit("only .zip archives are supported")
    if not archive.is_file():
        raise SystemExit(f"archive does not exist: {archive}")

    if args.output_dir is None:
        output_dir = vault / "raw" / archive.stem
    else:
        output_dir = resolve_vault_child(vault, args.output_dir)
    output_dir = ensure_within(output_dir, raw_dir, "archive output directory must stay under vault/raw")
    if output_dir.resolve() == raw_dir.resolve():
        raise SystemExit("archive output directory must be a subdirectory of vault/raw")
    if output_dir.exists() and not output_dir.is_dir():
        raise SystemExit(f"archive output path is not a directory: {rel(output_dir, vault)}")

    try:
        planned, skipped = collect_plan(vault, archive, output_dir)
    except zipfile.BadZipFile as exc:
        raise SystemExit(f"archive is not a valid ZIP file: {archive}") from exc

    if args.dry_run:
        print(f"DRY RUN: would extract {len(planned)} file(s) to {rel(output_dir, vault)}")
        for item in planned:
            print(f"- {rel(Path(item['target']), vault)} ({item['size_bytes']} bytes)")
        if skipped:
            print("Skipped packaging entries:")
            for name in skipped:
                print(f"- {name}")
        return 0

    manifest = extract_plan(vault, archive, output_dir, planned, skipped)
    print(f"extracted {len(planned)} file(s) to {rel(output_dir, vault)}")
    print(f"manifest appended to {rel(manifest, vault)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
