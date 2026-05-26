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

## Setup (for LLM Agents)

When setting up this project for the first time, do NOT install or modify
anything until the user confirms the plan.

### Phase 1 — Detect (silent, no changes)

Run these checks silently and compile a report:

| Check | How | What to note |
|-------|-----|--------------|
| Python | `python --version` | Installed: version → ok if ≥ 3.11; Missing or too old → need install |
| uv | `uv --version` | Installed or missing |
| git | `git --version` | Installed or missing |
| Repo already cloned | `Test-Path chaoxing-homework-review` (or `ls`) | Already exists or needs clone |
| .env configured | `Test-Path chaoxing-homework-review/.env` | Exists with non-placeholder `AI_API_KEY` or needs setup |
| Playwright browser | Check OS: Windows → has Edge (skip); other → needs `playwright install chromium` |

### Phase 2 — Report & Ask

Present the findings to the user as a checklist, marking each item ✅ (ready),
⚠️ (needs action), or ❌ (blocker). Then ask:

> 我将按以上计划操作，是否继续？
> Choose: "继续" / "跳过某步" / "我自己来"

Do NOT proceed until the user confirms.

### Phase 3 — Execute

Only after user confirmation, run the needed steps:

1. **Python** (if ❌): Tell the user to install Python 3.11+ from
   https://www.python.org/downloads/ and retry. Do NOT install Python yourself.

2. **uv** (if ⚠️): Follow https://uv.doczh.com/getting-started/installation/
   for the user's platform. Use the official install command.

3. **git clone** (if ⚠️):
   ```powershell
   git clone https://github.com/Yihe-ng/chaoxing-homework-review.git
   cd chaoxing-homework-review
   ```

4. **uv sync** (if ⚠️): Creates `.venv` and installs all dependencies.

5. **Playwright browser** (if ⚠️): `uv run playwright install chromium`.
   Skip on Windows (Edge is preinstalled and preferred).

6. **.env** (if ⚠️): Copy `.env.example` to `.env`, then ask the user to edit
   it and fill in `AI_API_KEY`. Tell them to register at
   https://platform.deepseek.com/api_keys (free tier available).
   **Never read or print the key value.** If `.env` already has a valid-looking
   key, skip this step.

7. **Verify** (always): `uv run python -m unittest discover -s tests`
   All 47 tests must pass. If any fail, report which tests failed and stop —
   do not proceed to collection or review.

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
4. If the user wants AI explanations, check that `.env` has `AI_API_KEY` set.
   Run `uv run homework-review` without `--dry-run` only after confirming the
   key and dry-run output look correct.

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
