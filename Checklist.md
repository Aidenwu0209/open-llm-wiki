# open-llm-wiki Evaluation Checklist

This checklist is for independent product, engineering, and content QA of
`open-llm-wiki`. It is intentionally concrete: each item should be tested with a
real vault, not only by reading the code.

Recommended test environments:

- Windows with Git Bash.
- A fresh clone of the repository.
- The example vault at `examples/minimal-vault`.
- A corpus vault with multiple PDFs or parsed Markdown files.
- A disposable vault created by `scripts/wiki_init.py`.

All commands on Windows should be run through Git Bash. Generated Markdown and
JSONL files must be UTF-8.

```bash
uv sync --dev --locked
```

## 1. Repository And Environment

- [ ] `uv sync --dev --locked` creates or updates the project-local `.venv`
      without requiring global Python package installs.
- [ ] `uv run python --version` runs from the local uv-managed environment.
- [ ] `uv run python scripts/check_quality.py` passes.
- [ ] `uv run python scripts/wiki_eval.py` passes.
- [ ] `bash -n setup.sh` passes.
- [ ] `git diff --check` reports no whitespace errors.
- [ ] `.github/workflows/validate.yml` runs the same core quality gates in CI.
- [ ] The repository contains no secrets, local tokens, private corpora, or
      machine-specific generated vault outputs.
- [ ] All Markdown, Python, YAML, and shell files open correctly as UTF-8.

## 2. Skill Packaging Quality

- [ ] `uv run python -m skills_ref.cli validate skills/wiki-ingest` passes.
- [ ] `uv run python -m skills_ref.cli validate skills/query-writeback` passes.
- [ ] `uv run python -m skills_ref.cli validate skills/wiki-lint` passes.
- [ ] Each `SKILL.md` has frontmatter `name` matching its folder name.
- [ ] Each skill description is specific enough for safe trigger behavior.
- [ ] Skills state their target task boundaries and do not over-trigger on
      unrelated writing, search, or generic Markdown editing tasks.
- [ ] Skills list the exact runtime scripts they depend on.
- [ ] Skills describe completion criteria, not only a happy path.
- [ ] Skills require reviewable output before durable writeback.

## 3. Vault Initialization

- [ ] `uv run python scripts/wiki_init.py <new-vault> --repo-root .` creates a
      complete vault structure.
- [ ] New vault includes `raw`, `drafts`, `sources`, `concepts`, `qa-reports`,
      `claims`, `templates`, `_state`, and `log-archive`.
- [ ] New vault includes `SCHEMA.md`, `index.md`, `log.md`, and
      `_state/id-counter.md`.
- [ ] New vault includes `_state/source-registry.jsonl`,
      `_state/growth-queue.jsonl`, and `_state/science-review-queue.jsonl`.
- [ ] New vault includes `.open-llm-wiki/scripts/` with the runtime scripts.
- [ ] Running `wiki_lint.py <new-vault> --fail-on p1` passes immediately after
      initialization.
- [ ] `uv run python scripts/wiki_obsidian_setup.py <new-vault> --dry-run
      --skip-downloads` reports planned Obsidian changes without writing files.
- [ ] `uv run python scripts/wiki_init.py <new-vault> --repo-root .
      --obsidian --obsidian-skip-downloads` creates `.obsidian/app.json`,
      `.obsidian/community-plugins.json`, `raw/inbox/`, and `sortspec.md`.
- [ ] `uv run python scripts/wiki_lint.py <new-vault> --obsidian --fail-on p1`
      reports Obsidian status without P0/P1 findings.
- [ ] Re-running initialization without `--force` does not overwrite existing
      user-edited files.
- [ ] Re-running initialization with `--force` overwrites only intended runtime
      or scaffold files.

## 4. PDF To Markdown Runtime

- [ ] `scripts/pdf_to_markdown.py --help` documents required API settings and
      output behavior.
- [ ] PDF conversion reads API endpoint and token from CLI arguments or
      environment variables rather than hardcoding credentials.
- [ ] PDF conversion writes Markdown and image assets only under the selected
      output directory.
- [ ] PDF conversion creates a manifest or traceable output that links source
      PDF, Markdown, image assets, warnings, and parser response status.
- [ ] Failed HTTP responses produce a clear non-zero exit and do not create a
      misleading successful Markdown file.
- [ ] Retry behavior works for transient network failures when configured.
- [ ] Large PDFs do not crash without a clear error message.
- [ ] Unicode text from parsed papers is preserved as UTF-8.
- [ ] Image download failures are reported without corrupting the Markdown
      document.
- [ ] `scripts/pdf_corpus_to_markdown.py --help` documents batch conversion
      options.
- [ ] Batch conversion can skip already converted PDFs.
- [ ] Batch conversion can resume after a partial failure.
- [ ] Batch conversion writes an audit log covering every attempted PDF.
- [ ] `scripts/pdf_corpus_report.py --help` documents corpus validation flags.
- [ ] Corpus report detects missing Markdown outputs.
- [ ] Corpus report detects suspiciously short parsed outputs.
- [ ] Corpus report detects parser warning patterns.

## 5. Corpus Ingest

- [ ] `scripts/wiki_ingest_corpus.py --help` describes source-page generation,
      QA report creation, concept page updates, and resume behavior.
- [ ] Ingest turns `raw/*_markdown/combined.md` into stable source pages.
- [ ] Ingest creates one `sources/LLM-NNNN.md` page per accepted source.
- [ ] Source IDs are unique, stable, and match filenames.
- [ ] Source frontmatter includes `id`, `title`, `status`, `created`,
      `updated`, `source`, and `tags`.
- [ ] Source body contains explicit evidence anchors or evidence tables.
- [ ] Ingest creates `qa-reports/LLM-NNNN.md` for each source.
- [ ] QA reports contain `verdict: PASS` only when criteria are met.
- [ ] Ingest creates contradiction reports for each source or ensures the lint
      gate can identify missing reports.
- [ ] Ingest updates `index.md` with source and concept links.
- [ ] Ingest updates `log.md` with traceable operations.
- [ ] Ingest does not delete raw PDFs or parsed Markdown.
- [ ] Resume mode avoids duplicating already ingested source pages.
- [ ] Resume mode continues after partial corpus progress.

## 6. Source Discovery And Deduplication

- [ ] `scripts/wiki_discover_sources.py --help` documents registry, report,
      arXiv query, and duplicate failure flags.
- [ ] Discovery scans raw files.
- [ ] Discovery scans parsed Markdown text near raw files.
- [ ] Discovery scans existing source pages.
- [ ] Discovery extracts arXiv IDs from filenames or document text.
- [ ] Discovery extracts DOI values from filenames or document text.
- [ ] Discovery computes SHA256 for raw files.
- [ ] Discovery normalizes title keys from parsed titles or source titles.
- [ ] Discovery can optionally call the arXiv API with `--arxiv-query`.
- [ ] Discovery writes `_state/source-registry.jsonl`.
- [ ] Discovery writes `_state/source-discovery-report.md`.
- [ ] Duplicate groups are reported by arXiv ID.
- [ ] Duplicate groups are reported by DOI.
- [ ] Duplicate groups are reported by SHA256.
- [ ] Duplicate groups are reported by normalized title key.
- [ ] `--fail-on-duplicates` exits non-zero when duplicates are present.
- [ ] Discovery never deletes raw files, source pages, or concept pages.
- [ ] Output paths outside the vault are rejected.

## 7. Claim Extraction

- [ ] `scripts/wiki_claims.py --help` documents output and report paths.
- [ ] Claim extraction reads stable source pages from `sources/`.
- [ ] Claim extraction writes `claims/claims.jsonl`.
- [ ] Claim extraction writes `claims/claim-report.md`.
- [ ] Every JSONL row is valid JSON.
- [ ] Every claim includes `source_id`, `claim_id`, `claim_type`, `predicate`,
      `object`, `evidence`, and `concepts`.
- [ ] Claim evidence points back to an existing source or raw evidence anchor.
- [ ] Metric claims include original `value`, `unit`, and `baseline` fields when
      available.
- [ ] Claims that are ambiguous or weakly grounded are marked `needs_review`.
- [ ] Output paths outside the vault are rejected.

## 8. Metric, Unit, Protocol, And Baseline Normalization

- [ ] `scripts/wiki_normalize_metrics.py --help` documents `--in-place`,
      output, and report behavior.
- [ ] Normalization writes `claims/normalized-claims.jsonl`.
- [ ] Normalization can update `claims/claims.jsonl` with `--in-place`.
- [ ] Normalization writes `claims/metric-normalization-report.md`.
- [ ] Metric claims get `metric_key`.
- [ ] Metric claims get `normalized_value` when a numeric value can be parsed.
- [ ] Metric claims get `normalized_unit`.
- [ ] Metric claims get `unit_family`.
- [ ] Metric claims get `baseline_key`.
- [ ] Metric claims get `protocol_key`.
- [ ] Ambiguous metrics receive `normalization_warnings`.
- [ ] Missing or unnormalized baselines are surfaced as warnings.
- [ ] Generic metric names are surfaced as warnings.
- [ ] Normalization does not invent missing scientific context.
- [ ] Output paths outside the vault are rejected.

## 9. Semantic QA

- [ ] `scripts/wiki_semantic_qa.py --help` documents severity thresholds.
- [ ] Semantic QA reads the current claim graph.
- [ ] Semantic QA verifies that referenced source IDs exist.
- [ ] Semantic QA verifies evidence paths or anchors are plausible.
- [ ] Semantic QA flags unsupported claims as P0 or P1.
- [ ] Semantic QA flags missing normalized metric values as P2.
- [ ] Semantic QA writes `qa-reports/semantic-qa-YYYY-MM-DD.md` with
      `--write-report`.
- [ ] `--fail-on p1` exits non-zero when P0/P1 issues exist.
- [ ] `--fail-on p2` exits non-zero when any P0/P1/P2 issue exists.
- [ ] Report output paths outside the vault are rejected.

## 10. Second-Pass Scientific Review

- [ ] `scripts/wiki_science_review.py --help` documents queue and report modes.
- [ ] Science review identifies claims with normalization warnings.
- [ ] Science review identifies claims marked `needs_review`.
- [ ] Science review identifies metric claims missing comparable baseline or
      protocol context.
- [ ] Science review writes `_state/science-review-queue.jsonl` with `--queue`.
- [ ] Science review writes `qa-reports/science-review-YYYY-MM-DD.md` with
      `--write-report`.
- [ ] Queue rows include `review_id`, `review_status`, `review_decision`,
      `reviewed_by`, `reviewed_at`, `review_reasons`, and `review_questions`.
- [ ] Review report uses `REVIEW_REQUIRED` when items need review.
- [ ] Review report uses `PASS` only when no items need review.
- [ ] `--fail-on-review-required` exits non-zero when review items exist.
- [ ] The system does not pretend a human or second LLM has approved items.
- [ ] Concept revision excludes review-required claims until explicitly marked
      `science_review: approved`.
- [ ] Report output paths outside the vault are rejected.

## 11. Contradiction Detection

- [ ] `scripts/wiki_contradictions.py --help` documents candidate detection and
      report behavior.
- [ ] Contradiction detection reads normalized claim fields when available.
- [ ] Numeric comparisons use normalized metric keys and units.
- [ ] Candidate conflicts are reported as candidates, not confirmed
      contradictions.
- [ ] Contradiction report explains reviewer policy for protocol, unit, and
      baseline compatibility.
- [ ] Explicit `[CONTRADICTION YYYY-MM-DD]` markers in concept pages are
      reported.
- [ ] `--fail-on-candidate` exits non-zero when candidates exist.
- [ ] Report output paths outside the vault are rejected.

## 12. Concept Revision

- [ ] `scripts/wiki_concept_revision.py --help` documents preview, apply, limit,
      and review-required behavior.
- [ ] Preview mode reports changed concept pages without writing files.
- [ ] Apply mode updates concept pages.
- [ ] Concept pages receive a `Semantic Claim Matrix`.
- [ ] Generated claim matrices cite source pages with wikilinks.
- [ ] Generated claim matrices include evidence pointers.
- [ ] Concept revision skips claims requiring second-pass review by default.
- [ ] `--include-review-required` includes unapproved review-required claims
      only when explicitly requested.
- [ ] Concept revision does not rewrite unrelated hand-authored sections.
- [ ] Concept revision appends traceable `log.md` entries when applied.
- [ ] Re-running concept revision is idempotent when inputs have not changed.

## 13. Durable Growth Queue

- [ ] `scripts/wiki_queue.py --help` documents `init`, `plan`, `enqueue`,
      `list`, and `run-due`.
- [ ] `init` creates or preserves `_state/growth-queue.jsonl`.
- [ ] `plan --cadence now` schedules immediate staged tasks.
- [ ] `plan --cadence daily` schedules the next daily maintenance wave.
- [ ] `plan --cadence weekly` schedules the next weekly maintenance wave.
- [ ] `plan --cadence monthly` schedules the next monthly maintenance wave.
- [ ] Planned actions include `discover`, `grow`, `science-review`,
      `concept-revision`, and `lint` when appropriate.
- [ ] Planned actions are staged a few minutes apart rather than all sharing one
      timestamp.
- [ ] Re-planning updates pending tasks instead of silently leaving stale due
      times.
- [ ] Running tasks are not overwritten by re-planning.
- [ ] `enqueue` rejects unknown actions.
- [ ] `run-due --dry-run` prints due tasks without mutating task status.
- [ ] `run-due` marks successful tasks `done`.
- [ ] `run-due` marks failed tasks `failed` and records `last_error`.
- [ ] Queue state remains valid JSONL after every operation.

## 14. Semantic Growth Orchestration

- [ ] `scripts/wiki_grow.py --help` documents all orchestration flags.
- [ ] `--discover-sources` refreshes the source registry before growth.
- [ ] `--ingest-corpus` ingests parsed corpus files before claims.
- [ ] `--plan-queue` updates the durable growth queue.
- [ ] `--queue-cadence` is passed to queue planning.
- [ ] `--science-review` writes review queue and report.
- [ ] Claims are extracted before normalization.
- [ ] Normalization runs before semantic QA.
- [ ] Semantic QA runs before concept revision.
- [ ] Science review runs before concept revision when requested.
- [ ] Contradiction scan runs after normalization.
- [ ] Concept revision runs in preview mode unless `--apply-concept-revision` is
      provided.
- [ ] Lint runs at the end unless `--skip-lint` is provided.
- [ ] `--skip-queue` prevents recursive queue planning when called by the queue
      runner.
- [ ] The full command succeeds on `examples/minimal-vault`.
- [ ] The full command succeeds on a multi-paper corpus vault with no P0/P1 lint
      findings.

## 15. Lint And Structural Validation

- [ ] `scripts/wiki_lint.py --help` documents severity thresholds.
- [ ] Lint fails P0 when required directories are missing.
- [ ] Lint fails P0 when required files are missing.
- [ ] Lint validates source frontmatter.
- [ ] Lint validates source filename and ID alignment.
- [ ] Lint validates source status for `sources/` and `drafts/`.
- [ ] Lint detects duplicate source IDs.
- [ ] Lint checks explicit evidence anchors.
- [ ] Lint validates concept frontmatter.
- [ ] Lint checks concept wikilinks.
- [ ] Lint checks per-source QA reports.
- [ ] Lint checks contradiction reports.
- [ ] Lint checks unresolved wikilinks.
- [ ] Lint checks missing index links.
- [ ] Lint checks log format.
- [ ] Lint flags stale time-sensitive claims older than 90 days.
- [ ] Lint validates `claims/claims.jsonl`.
- [ ] Lint validates `_state/growth-queue.jsonl`.
- [ ] Lint validates `_state/source-registry.jsonl`.
- [ ] Lint validates `_state/science-review-queue.jsonl`.
- [ ] `--fail-on p1` fails on P0 or P1 findings.
- [ ] `--fail-on p2` fails on P0, P1, or P2 findings.

## 16. Search And Query Writeback

- [ ] `scripts/wiki_search.py --help` documents vault, query, and limit usage.
- [ ] Search returns relevant source pages.
- [ ] Search returns relevant concept pages.
- [ ] Search respects the requested result limit.
- [ ] Search works on UTF-8 Markdown content.
- [ ] `scripts/wiki_writeback.py --help` documents target, query, body, and
      apply behavior.
- [ ] Writeback preview prints a reviewable diff without modifying the target.
- [ ] Writeback apply appends a `Query-Derived Note`.
- [ ] Writeback records the original user query.
- [ ] Writeback requires either `--body` or `--body-file`.
- [ ] Writeback target must stay inside the vault.
- [ ] Writeback target must be under `concepts/`.
- [ ] Writeback does not modify source pages or raw evidence.
- [ ] Writeback output remains readable after repeated applications.

## 17. Safety Boundaries And File Side Effects

- [ ] Runtime scripts never write outside the selected vault unless explicitly
      documented.
- [ ] Runtime scripts reject path traversal outputs such as `../outside.md`.
- [ ] Ingest and lint never delete raw evidence.
- [ ] Discovery never deletes or rewrites source pages.
- [ ] Claim extraction writes only under `claims/` unless a safe in-vault output
      path is explicitly provided.
- [ ] Normalization writes only under `claims/` unless a safe in-vault output
      path is explicitly provided.
- [ ] QA and review reports write only under `qa-reports/` unless a safe in-vault
      output path is explicitly provided.
- [ ] Queue files write only under `_state/`.
- [ ] Concept revision writes only under `concepts/` and `log.md`.
- [ ] Scripts produce non-zero exits for unsafe or invalid output paths.
- [ ] Scripts print clear errors that explain the safety boundary.
- [ ] No command requires destructive Git operations.

## 18. Minimal Vault Regression

- [ ] `uv run python scripts/wiki_lint.py examples/minimal-vault --fail-on p1`
      passes.
- [ ] `uv run python scripts/wiki_search.py examples/minimal-vault "attention transformer" --limit 2`
      returns `Attention Is All You Need`.
- [ ] `uv run python scripts/wiki_claims.py examples/minimal-vault` succeeds.
- [ ] `uv run python scripts/wiki_normalize_metrics.py examples/minimal-vault --in-place`
      succeeds.
- [ ] `uv run python scripts/wiki_semantic_qa.py examples/minimal-vault --write-report --fail-on p1`
      succeeds.
- [ ] `uv run python scripts/wiki_science_review.py examples/minimal-vault --queue --write-report`
      succeeds.
- [ ] `uv run python scripts/wiki_contradictions.py examples/minimal-vault --write-report`
      succeeds.
- [ ] `uv run python scripts/wiki_concept_revision.py examples/minimal-vault`
      succeeds in preview mode.
- [ ] `uv run python scripts/wiki_queue.py examples/minimal-vault plan --cadence weekly`
      creates or updates staged pending tasks.
- [ ] Re-running `uv run python scripts/wiki_eval.py` still passes after these
      operations.

## 19. Multi-Paper Corpus Regression

- [ ] A corpus with at least 20 PDFs can be converted or ingested without manual
      file renaming.
- [ ] Source discovery reports raw/source duplicate groups after ingest.
- [ ] Source registry contains one raw row per raw document.
- [ ] Source registry contains one source row per ingested source page.
- [ ] Claim extraction creates a non-empty claim graph.
- [ ] Metric normalization creates a non-empty metric normalization report.
- [ ] Semantic QA passes with no P0/P1 issues.
- [ ] Science review produces `REVIEW_REQUIRED` rather than fake approval when
      metrics or baselines need judgment.
- [ ] Contradiction scan reports candidates separately from confirmed
      contradictions.
- [ ] Concept revision updates concept matrices without inserting unapproved
      high-risk claims.
- [ ] Final lint passes with `--fail-on p1`.
- [ ] The generated vault can be opened in Obsidian with usable backlinks.
- [ ] Optional Obsidian profile does not replace source QA, claim graph,
      semantic QA, contradiction scan, or query writeback approval gates.

## 20. Documentation And User Experience

- [ ] `README.md` explains the purpose of the system clearly.
- [ ] `README.zh.md` matches the English README on core behavior.
- [ ] `QUICKSTART.md` can be followed by a new evaluator without guessing hidden
      steps.
- [ ] `SCHEMA.md` accurately describes vault structure and state files.
- [ ] `SHOWCASE.md` demonstrates the semantic growth loop.
- [ ] `AGENTS.md` gives safe operating guidance for agents.
- [ ] Documentation consistently describes the project as a long-term,
      self-growing LLM wiki system.
- [ ] Documentation does not overclaim automatic scientific correctness.
- [ ] Documentation explains that second-pass review is a gate, not a simulated
      approval.
- [ ] Documentation explains that raw evidence is immutable and append-only
      reports are preferred.
- [ ] Documentation explains how to enable the optional Obsidian profile and how
      to run `wiki_lint.py --obsidian`.

## 21. GitHub And Release Readiness

- [ ] A push to `main` triggers GitHub Actions.
- [ ] GitHub Actions `Validate` passes.
- [ ] CI validates skills.
- [ ] CI runs repository quality checks.
- [ ] CI smoke-tests runtime commands.
- [ ] CI checks `setup.sh` syntax.
- [ ] GitHub repository description and topics match the project purpose.
- [ ] README first screen explains what users can do immediately.
- [ ] License is present.
- [ ] No generated local `.venv`, private vault, or cloud parser token is tracked.
- [ ] The project can be cloned and evaluated on a clean machine.

## 22. Acceptance Gate

The project is ready for recommendation only when all required items below pass:

- [ ] Clean clone can run `uv sync --dev --locked`.
- [ ] All three skills validate.
- [ ] `scripts/check_quality.py` passes.
- [ ] `scripts/wiki_eval.py` passes.
- [ ] Minimal vault lint passes with zero P0/P1 findings.
- [ ] A multi-paper corpus run completes source discovery, claims,
      normalization, semantic QA, science review, contradiction scan, concept
      revision, and lint.
- [ ] Review-required claims are queued instead of silently written into durable
      synthesis.
- [ ] Unsafe output paths are rejected.
- [ ] GitHub Actions passes on `main`.
- [ ] The evaluator can explain what files changed in the vault and why.
