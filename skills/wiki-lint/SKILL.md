---
name: wiki-lint
description: Periodic wiki health check. Detects contradictions, orphan pages, missing cross-references, stale claims, format violations, and log archival. Designed for Cron execution.
version: 0.1.0
---

# Wiki Lint

Periodic health check for the LLM Wiki. Runs via Cron (daily 9:00 AM) or on-demand.

## What to Check

### 1. Format Compliance
- [ ] Every source page in `sources/` has complete frontmatter (id, title, status, created, source, tags)
- [ ] Every concept page in `concepts/` has at least id, title, status, sources
- [ ] No `status: draft` pages in `sources/` (should be in `drafts/`)
- [ ] All IDs are sequential (no gaps in LLM-NNNN series)

### 2. QA Coverage
- [ ] Every `status: stable` source page has a corresponding `qa-reports/LLM-NNNN.md`
- [ ] No qa-reports have been modified after creation (append-only check)
- [ ] Report any source page without QA report → alert chairman

### 3. Cross-Reference Integrity
- [ ] All `[[LLM-XXXX]]` links point to existing files
- [ ] All `[[concept-name]]` links point to existing concept pages
- [ ] Orphan detection: pages with no inbound links from other wiki pages
- [ ] index.md includes all source and concept pages

### 4. Log Health
- [ ] If `log.md` exceeds 30 days of entries → archive older entries to `log-archive/YYYY-MM.md`
- [ ] Log entries follow consistent format: `[YYYY-MM-DD HH:MM] action | file | who | description`

### 5. Content Quality (lightweight)
- [ ] Check for obviously stale claims (e.g., "latest" references older than 90 days)
- [ ] Check for contradiction markers (`[CONTRADICTION]` or `⚠️` flags)
- [ ] Suggest new concept pages for topics mentioned in 3+ sources but lacking a concept page

## Execution

### Via Cron (recommended)
```
schedule: "0 9 * * *"
task: "Read wiki-lint Skill and execute full lint check. Report issues to chairman via message."
```

### Via Manual Command
User says "lint the wiki" or "check wiki health" → load this Skill and execute.

## Output

1. **Console output**: Summary of checks (pass/fail per category)
2. **Alert to chairman**: Only if issues found — format:
   ```
   🔍 Wiki Lint Report
   ✅ Format: PASS
   ⚠️ QA Coverage: LLM-0042 missing QA report
   ✅ Cross-refs: PASS
   ✅ Log: PASS
   🔴 Actions needed: [list]
   ```
3. **Log entry**: Append to log.md: `[YYYY-MM-DD HH:MM] lint | full-check | cron | [summary]`
