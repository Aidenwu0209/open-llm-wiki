# QUICKSTART.md — Get Running in 5 Minutes

## Prerequisites

1. **OpenClaw** installed ([install guide](https://docs.openclaw.ai))
2. An AI model configured in `openclaw.json` (we use `glm-5.1`)
3. A workspace directory for your wiki

## Step 1: Install Skills

```bash
# Clone this repo
git clone https://github.com/yourusername/open-llm-wiki.git

# Copy all three skills to your OpenClaw skills directory
cp -r open-llm-wiki/skills/* ~/.openclaw-autoclaw/skills/

# Verify installation
ls ~/.openclaw-autoclaw/skills/
# Should show: wiki-ingest/  query-writeback/  wiki-lint/
```

## Step 2: Create Wiki Structure

```bash
# Create your wiki directory (name it whatever you want)
mkdir -p my-llm-wiki/{raw,sources,concepts,drafts,qa-reports,templates,_state,log-archive}

# Copy schema and templates
cp open-llm-wiki/SCHEMA.md my-llm-wiki/
cp open-llm-wiki/templates/* my-llm-wiki/templates/
```

## Step 3: Initialize State Files

Create `my-llm-wiki/_state/id-counter.md`:
```markdown
# ID Counter
next: 1
```

Create `my-llm-wiki/index.md`:
```markdown
# LLM Wiki Index

## Sources
| ID | Title | Tags |

## Concepts
| Concept | Sources |
```

Create `my-llm-wiki/log.md`:
```markdown
# Wiki Log
```

## Step 4: Configure Your Agent

Add to your `AGENTS.md` (or equivalent):

```markdown
## Wiki Rules
- Read `SCHEMA.md` before any wiki operation
- One paper at a time (serial ingestion)
- QA must use independent sub-agent (never self-evaluate)
- QA score ≥ 7.0 required to promote
- Always cite sources: [[LLM-XXXX]]
```

## Step 5: Ingest Your First Paper

Drop a PDF into `raw/` and tell your agent:

```
Ingest this paper: raw/my-paper.pdf
```

The agent will:
1. Parse the PDF (PyMuPDF for files ≥2MB, PaddleOCR for smaller)
2. Write a draft source page
3. Self-check the draft
4. Spawn an independent QA sub-agent
5. Fix issues (if any)
6. Promote to `sources/`
7. Update concept pages and `index.md`
8. Run contradiction check
9. Log the operation

## Step 6: Query Your Wiki

Ask your agent questions about wiki content:

```
What are the key architectural innovations in DeepSeek-V3?
```

If the answer synthesizes from 3+ sources, the agent will automatically write it back to the relevant concept page.

## Step 7: Set Up Lint (Optional)

Add to your `HEARTBEAT.md` or cron:

```markdown
- [ ] Run wiki lint: check format, QA coverage, cross-references
```

## Configuration Options

### Sub-Agent Model

We recommend `glm-5.1` for QA and contradiction detection sub-agents. In your spawn calls:

```
model: glm-5.1
mode: run
runTimeoutSeconds: 180
```

### PDF Parser Selection

| File Size | Parser | Config |
|-----------|--------|--------|
| < 2MB | PaddleOCR cloud API | Requires API key in environment |
| ≥ 2MB | PyMuPDF (local) | No config needed |

### QA Threshold

Default: 7.0/10. Adjust in your `SCHEMA.md` if needed.

## Common Workflows

### Ingest a batch of papers
```
Ingest these papers one at a time:
1. raw/paper-a.pdf
2. raw/paper-b.pdf
3. raw/paper-c.pdf
```
*(Agent processes them serially, one at a time)*

### Check wiki health
```
Run a wiki lint check
```

### Query and grow
```
How did position encoding evolve from Transformer to RoPE to ALiBi?
```
*(Answer comes from wiki + writeback if 3+ sources cited)*

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| QA sub-agent returns no file | Model unavailable | Switch to glm-5.1 |
| PaddleOCR timeout | File too large | Use PyMuPDF (≥2MB files) |
| Concept page is a dump | No periodic revision | Run concept revision manually |
| Missing QA report | Skipped QA step | Never skip QA. Never. | 
