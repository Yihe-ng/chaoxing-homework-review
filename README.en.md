# Chaoxing Homework Export & Review Assistant

> Collect completed Chaoxing homework, generate AI explanations, output Word + Markdown review docs.

<!-- README-I18N:START -->
[中文](./README.md) | **English**
<!-- README-I18N:END -->

Export completed homework from Chaoxing (超星学习通), generate per-question
explanations via the DeepSeek API, and output review-ready Word and Markdown
documents.

Two-stage pipeline:

```
Collection                              Review
Playwright manual login                 Read raw JSON
  ↓                                       ↓
requests with saved cookies scrape        Deduplicate, merge, clean questions
  ↓                                       ↓
Interactive course → homework selection   DeepSeek API generates explanations
  ↓                                       ↓
Export JSON                              DOCX + Markdown + review checklist
```

> **Safety boundary**: This tool does not automate login, submission, or access
> bypass. It only reads pages you have permission to access.

## Setup

**Install uv** (if not already installed): [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/)

Install dependencies:

```powershell
uv sync
```

Browser note: Playwright prefers your system's built-in Microsoft Edge browser,
so no extra install is needed on Windows. If your system has neither Edge nor
Chrome, install the Playwright-managed Chromium:

```powershell
uv run playwright install chromium
```

**Get an API key**: This project uses [DeepSeek](https://platform.deepseek.com/)
by default (register and create a key on the
[API Keys](https://platform.deepseek.com/api_keys) page). It also works with
any OpenAI Chat Completions API-compatible provider (OpenAI, Groq, etc.) —
just change `AI_BASE_URL` and `AI_MODEL` in `.env`.

**Configure `.env`**: Rename `.env.example` to `.env` and edit it with your key:

```text
AI_API_KEY=your-api-key
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-v4-flash
AI_MAX_TOKENS=2000
DOCX_FONT=Microsoft YaHei
```

Set `AI_API_KEY` in `.env`. `DEEPSEEK_API_KEY` and `OPENAI_API_KEY` are also
supported as fallbacks.

`CHAOXING_*` variables have built-in defaults and are optional — see
[Configuration Reference](#configuration-reference).

**Let an AI agent set it up:** Copy and paste the following into Claude Code, Cursor,
Cline, or any AI coding tool. The agent will detect your environment first, show a
report, and ask for confirmation before making any changes:

```text
Follow https://raw.githubusercontent.com/Yihe-ng/chaoxing-homework-review/main/skills/homework-review/SKILL.md to install and configure this project.
```

## Usage

### Interactive Collection (primary)

Launch the interactive collector:

```powershell
uv run main.py
```

**Workflow:**

1. **Login** — A browser window opens to the Chaoxing login page. Complete
   login (QR code, phone, or university SSO are all supported), then return to
   the terminal and press Enter.
2. **Choose courses** — Enter a keyword to filter (for example, `计组`), then
   check the courses you want to collect.
3. **Choose homework** — All "completed" homework is pre-selected. Confirm to
   proceed.
4. **Collection** — The tool scrapes each homework page for questions, options,
   answers, and scores, saving them as JSON.
5. **Generate review docs** — After collection, you are prompted to generate
   review documents. Confirming calls the DeepSeek API for per-question
   explanations and outputs Word and Markdown files.

Login state is saved to `.local/chaoxing_state.json`. Subsequent runs skip the
login step. If the session expires, rerun `uv run main.py` and log in again.

**Common options:**

| Option | Effect |
|--------|--------|
| `--course "计算机组成与结构"` | Skip course selection, match by keyword (repeatable) |
| `--yes` | Skip all interactive prompts, use defaults |
| `--no-review` | Collect JSON only, without generating review documents |
| `--verify-answers` | Enable AI answer verification to flag potential errors |
| `--output-dir "my-output"` | Custom output directory (default: `output`) |

**Examples:**

```powershell
# Specific course + skip prompts + verify answers
uv run main.py --course "计算机组成与结构" --yes --verify-answers

# Collect only, no review
uv run main.py --course "人工智能基础" --no-review
```

### Generate Review Docs from Existing JSON

If you already have JSON exports, you can generate review documents directly.

Run a dry-run first to check the input without calling the API:

```powershell
uv run homework-review "output/人工智能基础/raw" --dry-run --output-dir "output/人工智能基础/review"
```

Then run with API calls to generate explanations:

```powershell
uv run homework-review "output/人工智能基础/raw" --output-dir "output/人工智能基础/review" --verify-answers
```

**Options:**

| Option | Effect |
|--------|--------|
| `--dry-run` | Skip API calls, use placeholders (quick validation) |
| `--verify-answers` | Let the model independently check exported answers |
| `--limit N` | Process only the first N questions (for testing) |
| `--title "Review Notes"` | Custom document title |
| `--output-dir "path"` | Output directory |
| `--cache "path"` | Explanation cache file path |

## Output Structure

After collection and review, the output directory looks like:

```text
output/
  计算机组成与结构/
    raw/                              # Collected raw JSON
      第一章作业.json
      第三章 总线作业.json
    review/                           # Review documents
      计算机组成与结构-完整复习资料.docx  # Word document
      计算机组成与结构-完整复习资料.md    # Markdown document
      questions.enriched.json         # Enriched JSON with explanations
      explanations.cache.json         # Explanation cache (reused on reruns)
      review-needed.md                # Questions flagged for manual review
```

**File descriptions:**

| File | Purpose |
|------|---------|
| `.docx` | Formatted Word review document, ready for print or WPS/Word |
| `.md` | Markdown format for note-taking apps (Obsidian, Notion, etc.) |
| `questions.enriched.json` | Structured question data with full AI explanations |
| `explanations.cache.json` | Cache reused across runs to save API costs |
| `review-needed.md` | Questions whose answers may be incorrect, with model assessment |

**AI explanation fields:**

| Field | Content |
|-------|---------|
| Why it's correct | Reasoning for the correct answer (80–150 chars) |
| Why others are wrong | Distractor analysis for each wrong option |
| Review trigger | One-line cue for identifying the answer in an exam |
| Knowledge points | Related concepts with explanations (1–4 items) |
| Judgment principles | How to approach similar questions (1–4 items) |

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_API_KEY` | — | AI API key (required) |
| `AI_BASE_URL` | `https://api.deepseek.com` | API endpoint |
| `AI_MODEL` | `deepseek-v4-flash` | Model name |
| `AI_MAX_TOKENS` | `2000` | Max tokens per request |
| `AI_TEMPERATURE` | `0.2` | Generation temperature |
| `AI_THINKING` | `disabled` | DeepSeek thinking mode |
| `DOCX_FONT` | `Microsoft YaHei` | Word document font |
| `VERIFY_ANSWERS` | `false` | Whether to independently verify exported answers (overridable via `--verify-answers`) |
| `CHAOXING_STATE_PATH` | `.local/chaoxing_state.json` | Login state file |
| `CHAOXING_HEADLESS` | `false` | Run browser in headless mode |
| `CHAOXING_OUTPUT_DIR` | `output` | Collection output root |
| `CHAOXING_REVIEW_AFTER_COLLECT` | `true` | Prompt for review after collection |

> DeepSeek aliases are also supported: `DEEPSEEK_API_KEY`,
> `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`.

## For AI Coding Assistants

The `skills/homework-review/` directory contains LLM workflow instructions for
OpenCode, Claude Code, Cursor, Cline, and similar tools. The skill enforces
safety boundaries: no automated login, no access bypass, no API key submission.

**Keywords**: Chaoxing, homework export, homework review, exam review, AI explanations, DeepSeek, DOCX, Markdown, study notes

## Development

```powershell
# Run tests
uv run python -m unittest discover -s tests

# Install Playwright browser (only needed without Edge/Chrome)
uv run playwright install chromium
```

## License

[MIT](./LICENSE)
