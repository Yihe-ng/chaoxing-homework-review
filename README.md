# Homework Review

Homework Review turns manually exported Chaoxing/ScriptCat homework JSON files
into review documents. It merges questions, cleans formatting, deduplicates
items, generates missing explanations with a DeepSeek-compatible API, and
exports DOCX, Markdown, and enriched JSON.

This project intentionally does not automate Chaoxing login, submission, or
access bypass. Export the JSON files yourself from pages you are allowed to
access, then run this tool locally.

## Setup

Install dependencies with uv:

```powershell
uv sync
```

Configure DeepSeek or another OpenAI-compatible provider with environment
variables:

```powershell
$env:AI_API_KEY="your-api-key"
$env:AI_BASE_URL="https://api.deepseek.com"
$env:AI_MODEL="deepseek-v4-flash"
```

For local use, you can also create a `.env` file in the project directory. The
file is ignored by git, so it is safer than pasting keys into commands:

```powershell
Copy-Item .env.example .env
```

Then edit `.env`:

```text
AI_API_KEY=your-deepseek-api-key
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-v4-flash
AI_MAX_TOKENS=2000
DOCX_FONT=Microsoft YaHei
```

The API request uses JSON output mode when supported by the provider. New AI
explanations are stored as structured fields:

- `correct_reason`: why the correct answer is correct.
- `wrong_options`: why the other options are not selected.
- `knowledge_points`: related concepts to review.
- `principles`: related principles or judging methods.

You can also use DeepSeek-specific aliases:

```powershell
$env:DEEPSEEK_API_KEY="your-api-key"
$env:DEEPSEEK_MODEL="deepseek-v4-flash"
```

## Usage

Run a dry-run first. This creates review files without calling the API:

```powershell
uv run homework-review "人工智能理论作业" --dry-run --output-dir "人工智能理论作业\output"
```

Then generate AI explanations:

```powershell
uv run homework-review "人工智能理论作业" --output-dir "人工智能理论作业\output"
```

The output directory contains:

- `questions.enriched.json`: normalized questions and explanations.
- `explanations.cache.json`: explanation cache for future runs.
- `<title>.md`: Markdown review notes.
- `<title>.docx`: Word review document.

## Development

Run tests with uv:

```powershell
uv run python -m unittest discover -s tests
```
