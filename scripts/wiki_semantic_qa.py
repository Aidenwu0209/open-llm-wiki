#!/usr/bin/env python3
"""Run semantic-quality checks over extracted wiki claims."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wiki_common import SOURCE_ID_RE, ensure_within, json_dump, read_text, write_text

VALID_VERDICTS = frozenset({"unreviewed", "supported", "weak", "contradicted", "retracted", "stale"})
EVIDENCE_QUOTE_MAX_LEN = 300


@dataclass
class Issue:
    priority: str
    subject: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"priority": self.priority, "subject": self.subject, "message": self.message}


def load_claims(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise SystemExit(f"claims file not found: {path}")
    claims = []
    for number, line in enumerate(read_text(path).splitlines(), 1):
        if not line.strip():
            continue
        try:
            claims.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"invalid JSONL at {path}:{number}: {exc}") from exc
    return claims


def save_claims(path: Path, claims: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in claims)
    write_text(path, text)


def compute_evidence_hash(evidence_quote: str) -> str:
    import hashlib
    return hashlib.sha256(evidence_quote.encode("utf-8")).hexdigest()[:16]


def verify_evidence_quote(claim: dict[str, object]) -> str:
    """Return verdict based on evidence_quote integrity checks."""
    evidence_quote = str(claim.get("evidence_quote", ""))
    if not evidence_quote:
        return "weak"
    if len(evidence_quote) > EVIDENCE_QUOTE_MAX_LEN:
        return "weak"
    stored_hash = str(claim.get("evidence_hash", ""))
    if stored_hash and stored_hash != compute_evidence_hash(evidence_quote):
        return "weak"
    anchor = str(claim.get("anchor") or claim.get("evidence", ""))
    if anchor:
        return "supported"
    return "unreviewed"


def assign_verdicts(claims: list[dict[str, object]], vault: Path) -> list[dict[str, object]]:
    """Verify evidence quotes and assign verdicts to claims."""
    source_ids = {path.stem for path in (vault / "sources").glob("LLM-*.md")}
    for claim in claims:
        current_verdict = str(claim.get("verdict", "unreviewed"))
        if current_verdict == "stale":
            continue
        source_id = str(claim.get("source_id", ""))
        if source_id not in source_ids:
            claim["verdict"] = "stale"
            claim["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            continue
        new_verdict = verify_evidence_quote(claim)
        claim["verdict"] = new_verdict
        claim["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return claims


def evidence_target(vault: Path, evidence: str) -> tuple[Path | None, int | None, str]:
    target = evidence.split("#", 1)[0].strip()
    if not target or target.startswith("http"):
        return None, None, ""
    if "/" not in target and "\\" not in target and not target.endswith((".md", ".txt", ".pdf", ".jsonl")):
        return None, None, ""
    path = (vault / target).resolve()
    try:
        path.relative_to(vault.resolve())
    except ValueError:
        return None, None, ""
    line_match = re.search(r"#L(\d+)", evidence)
    line_number = int(line_match.group(1)) if line_match else None
    fragment = evidence.split("#", 1)[1].strip() if "#" in evidence and line_number is None else ""
    return path, line_number, fragment


def slug(text: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s-]+", "-", clean).strip("-")


def heading_exists(path: Path, fragment: str) -> bool:
    if not fragment or path.suffix.lower() != ".md":
        return True
    expected = fragment.strip().lower()
    expected_slug = slug(fragment)
    for line in read_text(path).splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        heading = match.group(1).strip().lower()
        if expected == heading or expected_slug == slug(heading):
            return True
    return False


def comparable_evidence_line(text: str) -> str:
    """Normalize raw Markdown line text for visibility checks.

    Parsed PDF text can contain literal angle-bracket tokens such as
    `<tile_newline>` between a number and unit. Source pages display the cleaned
    claim value, so the QA check should compare against the same cleaned view
    instead of requiring byte-for-byte raw-line visibility.
    """
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_qualitative_metric_placeholder(claim: dict[str, object]) -> bool:
    if claim.get("claim_type") != "metric":
        return False
    metric_key = str(claim.get("metric_key", "")).strip().lower()
    object_text = str(claim.get("object", "")).strip().lower()
    has_value = claim.get("value") not in {None, ""}
    has_normalized_value = claim.get("normalized_value") not in {None, ""}
    return metric_key == "qualitative" and object_text == "qualitative claim" and not has_value and not has_normalized_value


def check_claims(vault: Path, claims: list[dict[str, object]]) -> list[Issue]:
    issues: list[Issue] = []
    source_ids = {path.stem for path in (vault / "sources").glob("LLM-*.md")}
    claims_by_source: dict[str, int] = {}
    for claim in claims:
        source_id = str(claim.get("source_id", ""))
        subject = str(claim.get("claim_id") or source_id or "claim")
        if not SOURCE_ID_RE.fullmatch(source_id):
            issues.append(Issue("P1", subject, "claim has invalid or missing source_id"))
            continue
        claims_by_source[source_id] = claims_by_source.get(source_id, 0) + 1
        if source_id not in source_ids:
            issues.append(Issue("P1", subject, f"claim points to missing source {source_id}"))
        evidence = str(claim.get("evidence", ""))
        if not evidence:
            issues.append(Issue("P1", subject, "claim has no evidence anchor"))
            continue
        if claim.get("claim_type") == "metric" and "normalized_value" not in claim:
            issues.append(Issue("P2", subject, "metric claim has not been normalized"))

        # Claim ledger: evidence_quote validation
        evidence_quote = str(claim.get("evidence_quote", ""))
        if not evidence_quote:
            issues.append(Issue("P2", subject, "claim has no evidence_quote"))

        # Claim ledger: evidence_hash validation
        stored_hash = str(claim.get("evidence_hash", ""))
        if evidence_quote and stored_hash:
            expected_hash = compute_evidence_hash(evidence_quote)
            if stored_hash != expected_hash:
                issues.append(Issue("P1", subject, f"evidence_hash mismatch: stored={stored_hash} expected={expected_hash}"))

        # Claim ledger: verdict validation
        verdict = str(claim.get("verdict", "unreviewed"))
        if verdict not in VALID_VERDICTS:
            issues.append(Issue("P1", subject, f"invalid verdict: {verdict}"))

        path, line_number, fragment = evidence_target(vault, evidence)
        if path is None:
            issues.append(Issue("P2", subject, f"evidence is human-readable but not machine-resolvable: {evidence}"))
            continue
        if not path.exists():
            issues.append(Issue("P1", subject, f"evidence path does not exist: {evidence}"))
            continue
        if not heading_exists(path, fragment):
            issues.append(Issue("P1", subject, f"evidence heading anchor does not exist: {evidence}"))
            continue
        if line_number is not None:
            lines = read_text(path).splitlines()
            if line_number < 1 or line_number > len(lines):
                issues.append(Issue("P1", subject, f"evidence line is out of range: {evidence}"))
                continue
            value = claim.get("object")
            if (
                value
                and str(value) not in comparable_evidence_line(lines[line_number - 1])
                and claim.get("claim_type") == "metric"
                and not is_qualitative_metric_placeholder(claim)
            ):
                issues.append(Issue("P1", subject, f"metric value is not visible on anchored line: {evidence}"))
    for source_id in sorted(source_ids):
        if claims_by_source.get(source_id, 0) == 0:
            issues.append(Issue("P1", source_id, "stable source has no extracted claims"))
    return issues


def markdown_report(vault: Path, claims_path: Path, claims: list[dict[str, object]], issues: list[Issue]) -> str:
    p0 = sum(1 for issue in issues if issue.priority == "P0")
    p1 = sum(1 for issue in issues if issue.priority == "P1")
    p2 = sum(1 for issue in issues if issue.priority == "P2")
    verdict = "PASS" if p0 == 0 and p1 == 0 else "FAIL"
    lines = [
        "# Semantic QA Report",
        f"- date: {datetime.now().strftime('%Y-%m-%d')}",
        f"- vault: {vault}",
        f"- claims: {len(claims)}",
        f"- p0: {p0}",
        f"- p1: {p1}",
        f"- p2: {p2}",
        f"- verdict: {verdict}",
        "",
        "## Findings",
    ]
    if not issues:
        lines.append("- none")
    else:
        for issue in issues:
            lines.append(f"- [{issue.priority}] {issue.subject}: {issue.message}")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            f"- claims file: `{claims_path.as_posix()}`",
            "- P1 means the claim graph is not safe enough for autonomous writeback.",
            "- P2 means the claim is usable but should be improved by a future reviewer.",
        ]
    )
    return "\n".join(lines) + "\n"


def should_fail(issues: list[Issue], fail_on: str) -> bool:
    priorities = {issue.priority for issue in issues}
    if fail_on == "none":
        return False
    if fail_on == "p0":
        return "P0" in priorities
    if fail_on == "p1":
        return bool(priorities.intersection({"P0", "P1"}))
    if fail_on == "p2":
        return bool(priorities.intersection({"P0", "P1", "P2"}))
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Check extracted claims against source evidence.")
    parser.add_argument("vault", type=Path)
    parser.add_argument("--claims", type=Path, help="Defaults to <vault>/claims/claims.jsonl.")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--report", type=Path, help="Defaults to <vault>/qa-reports/semantic-qa-YYYY-MM-DD.md.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument(
        "--fail-on",
        choices=["none", "p0", "p1", "p2"],
        default="p1",
        help=(
            "Failure threshold: none never exits non-zero; p0 fails on P0; "
            "p1 fails on P0/P1; p2 fails on P0/P1/P2. Defaults to p1."
        ),
    )
    parser.add_argument(
        "--assign-verdicts",
        action="store_true",
        help="Verify evidence quotes and assign verdicts (supported/weak/unreviewed) to claims.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="When used with --assign-verdicts, write updated claims back to the claims file.",
    )
    args = parser.parse_args()

    vault = args.vault.resolve()
    claims_path = (args.claims or vault / "claims" / "claims.jsonl").resolve()
    claims = load_claims(claims_path)

    if args.assign_verdicts:
        claims = assign_verdicts(claims, vault)
        if args.in_place:
            save_claims(claims_path, claims)

    issues = check_claims(vault, claims)
    if args.format == "json":
        print(json_dump({"claims": len(claims), "issues": [issue.as_dict() for issue in issues]}))
    else:
        print(markdown_report(vault, claims_path, claims, issues))
    if args.write_report:
        report = ensure_within(
            args.report or vault / "qa-reports" / f"semantic-qa-{datetime.now().strftime('%Y-%m-%d')}.md",
            vault,
            "semantic QA report must stay inside the vault",
        )
        write_text(report, markdown_report(vault, claims_path, claims, issues))
        print(f"report: {report}")
    return 1 if should_fail(issues, args.fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
