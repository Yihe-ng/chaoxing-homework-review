---
name: homework-review
description: Use when processing manually exported Chaoxing/ScriptCat homework JSON files into AI-explained DOCX or Markdown review materials, especially when the user asks to merge homework questions, generate explanations through DeepSeek or an OpenAI-compatible API, cache explanations, or build a unified review document.
---

# Homework Review

Use this skill to process Chaoxing homework exports that the user has already
downloaded as JSON. Do not automate login, submission, or access bypass. Treat
the Python tool as the deterministic engine and use the Agent for supervision,
configuration, and review.

## Workflow

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

   Accept `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_MODEL` as
   DeepSeek-specific aliases.

   A local `.env` file is also supported. Use `.env.example` as the template,
   and never print or commit the user's real API key.

5. Run the paid/API generation only after dry-run succeeds:

   ```powershell
   uv run homework-review "<input-dir>" --output-dir "<output-dir>"
   ```

6. Report question count, output paths, and whether explanations came from AI,
   cache, platform data, or dry-run placeholders.

## Defaults

- Default API base URL: `https://api.deepseek.com`.
- Default model: `deepseek-v4-flash`.
- Recommended output directory: `<input-dir>\output`.
- Cache file: `<output-dir>\explanations.cache.json`.
- AI explanations use JSON output mode and include correct-answer reasoning,
  wrong-option analysis, knowledge points, and related principles.

## Safety boundaries

- Do not store API keys in files.
- Do not modify the user's exported JSON files.
- Do not call the API when `--dry-run` is requested.
- Stop and report the file path if a JSON file cannot be parsed.
- Keep generated review files out of version control unless the user asks to
  track them.

## Verification

Run these checks before saying the work is complete:

```powershell
uv run python -m unittest discover -s tests
uv run homework-review "<input-dir>" --dry-run --output-dir "<output-dir>"
```
