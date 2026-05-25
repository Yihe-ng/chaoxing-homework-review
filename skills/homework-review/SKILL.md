---
name: homework-review
description: Use when the user wants to collect completed homework from Chaoxing (超星学习通), or process manually exported Chaoxing/ScriptCat homework JSON files into AI-explained DOCX or Markdown review materials. Covers interactive collection via main.py (Playwright login → course selection → homework scraping → review generation) and standalone review via homework-review CLI (merge questions, generate explanations through DeepSeek or an OpenAI-compatible API, cache explanations, build unified review documents).
---

# Homework Review

Use this skill to collect Chaoxing homework or process existing JSON exports.
Do not automate login, submission, or access bypass. Treat the Python tool as
the deterministic engine and use the Agent for supervision, configuration, and
review.

## Two-Stage Pipeline

```
Collection (main.py)                   Review (homework-review)
Playwright manual login                Read raw JSON
  ↓                                      ↓
requests scrape courses/homework        Deduplicate, merge, clean
  ↓                                      ↓
Interactive course → homework select    DeepSeek API explanations
  ↓                                      ↓
Export raw JSON                        DOCX + Markdown + checklist
```

## Workflow

### Primary: Interactive Collection

Run the interactive collector to go from login to review docs in one pass:

```powershell
uv run main.py
```

The tool opens a browser for manual Chaoxing login, lists courses, lets the user
choose completed homework, scrapes question data, and optionally generates
review documents immediately. See `README.zh.md` for the full walkthrough.

Useful options:

```powershell
uv run main.py --course "计算机组成与结构" --yes --verify-answers
uv run main.py --no-review
```

### Secondary: Review Existing JSON

When the user already has raw JSON files (from `main.py` or manual export):

1. Inspect the target directory and count `.json` files.
2. Run a dry-run first:

   ```powershell
   uv run homework-review "<input-dir>" --dry-run --output-dir "<output-dir>"
   ```

3. Confirm the dry-run created `.docx`, `.md`, and `questions.enriched.json`.
4. If the user wants AI explanations, check environment variables:

   ```powershell
   $env:AI_API_KEY
   $env:AI_BASE_URL
   $env:AI_MODEL
   ```

   `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_MODEL` are accepted
   as fallback aliases. `OPENAI_API_KEY` is also supported.

   A local `.env` file is supported. Rename `.env.example` to `.env` and edit
   it. Never print or commit the user's real API key.

5. Run the paid/API generation only after dry-run succeeds:

   ```powershell
   uv run homework-review "<input-dir>" --output-dir "<output-dir>"
   ```

6. Report question count, output paths, and whether explanations came from AI,
   cache, platform data, or dry-run placeholders.

## Defaults

- Default API base URL: `https://api.deepseek.com`.
- Default model: `deepseek-v4-flash`.
- Collection output: `output/<course>/raw/`.
- Review output: `output/<course>/review/`.
- Cache file: `<review-dir>/explanations.cache.json`.
- AI explanations use JSON output mode and include correct-answer reasoning,
  wrong-option analysis, review tips, knowledge points, and judgment principles.

## Safety Boundaries

- Do not store API keys in files.
- Do not automate Chaoxing login or submission.
- Do not modify the user's exported JSON files.
- Do not call the API when `--dry-run` is requested.
- Stop and report the file path if a JSON file cannot be parsed.
- Keep generated review files and `.local/` out of version control.
- Login state is saved to `.local/chaoxing_state.json` (git-ignored).

## Verification

Run these checks before saying the work is complete:

```powershell
uv run python -m unittest discover -s tests
uv run homework-review "<input-dir>" --dry-run --output-dir "<output-dir>"
```
