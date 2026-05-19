"""Build review documents from Chaoxing homework exports."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Iterable


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
QUESTION_FONT_SIZE_PT = 13
CALLOUT_FONT_SIZE_PT = 12


def normalize_question_text(text: str) -> str:
    text = re.sub(r"^\s*\d+[.．、]\s*", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def normalize_option(option: str) -> str:
    option = re.sub(r"\s+", " ", option or "").strip()
    option = re.sub(r"^([A-Z])\s*[.．、]\s*", r"\1. ", option)
    option = re.sub(r"^([A-Z])\. \1\s*[.．、]\s*", r"\1. ", option)
    return option


def normalize_answer(answer: object) -> str:
    text = str(answer or "").strip()
    parts = [part.strip() for part in text.split("###") if part.strip()]
    return "；".join(parts) if parts else text


def normalize_question(raw: dict, meta: dict | None = None, source_file: str = "") -> dict:
    meta = meta or {}
    question = dict(raw)
    question["courseName"] = question.get("courseName") or meta.get("courseName", "")
    if source_file:
        question["sourceFile"] = source_file
    question["question"] = normalize_question_text(question.get("question", ""))
    question["options"] = [
        normalize_option(option) for option in question.get("options", []) if option
    ]
    question["answer"] = normalize_answer(question.get("answer", ""))
    return question


def question_key(question: dict) -> str:
    payload = {
        "type": question.get("type", ""),
        "question": normalize_question_text(question.get("question", "")),
        "options": [normalize_option(item) for item in question.get("options", [])],
        "answer": question.get("answer", ""),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_questions(input_path: Path | str) -> list[dict]:
    root = Path(input_path)
    files = sorted(root.rglob("*.json")) if root.is_dir() else [root]
    questions: list[dict] = []
    seen: set[str] = set()

    for file_path in files:
        if file_path.name.endswith(".enriched.json"):
            continue
        data = json.loads(file_path.read_text(encoding="utf-8-sig"))
        meta = data.get("meta", {}) if isinstance(data, dict) else {}
        raw_questions = data.get("questions", data if isinstance(data, list) else [])
        for raw in raw_questions:
            question = normalize_question(raw, meta, file_path.name)
            key = question_key(question)
            if key in seen:
                continue
            question["id"] = key[:12]
            seen.add(key)
            questions.append(question)

    return questions


def load_cache(cache_path: Path | None) -> dict[str, dict]:
    if not cache_path or not cache_path.exists():
        return {}
    return json.loads(cache_path.read_text(encoding="utf-8"))


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_dotenv(path: Path | str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def build_prompt(question: dict) -> list[dict]:
    options = "\n".join(question.get("options", [])) or "无"
    user = f"""题型：{question.get("type", "")}
题目：{question.get("question", "")}
选项：
{options}
已知正确答案：{question.get("answer", "")}

请生成适合复习背诵的中文解析，并严格输出 json。"""
    return [
        {
            "role": "system",
            "content": (
                "你是课程复习助手。根据题目、选项和已知正确答案生成解析，"
                "不要更改答案。必须只输出合法 json，不要输出 Markdown。"
                "所有内容都要面向正在复习的学生，像老师讲解这道题一样。"
                "json 格式示例："
                '{"correct_reason":"为什么正确答案正确",'
                '"wrong_options":[{"option":"A","reason":"为什么不选，干扰点在哪"}],'
                '"knowledge_points":["这道题涉及的知识点，需展开说明其含义和复习时要抓住什么"],'
                '"principles":["这道题背后的判断原理，需说明遇到同类题怎么判断"]}。'
                "correct_reason 控制在 80 到 150 字；wrong_options 覆盖明显错误选项；"
                "knowledge_points 和 principles 各给 1 到 4 条，每条 40 到 90 字；"
                "不要只写标签或名词短语，要展开说明为什么这个知识点与题目有关，"
                "以及学生复习时应该记住的判断线索。"
            ),
        },
        {"role": "user", "content": user},
    ]


def api_settings_from_env() -> dict[str, str]:
    api_key = (
        os.getenv("AI_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    if not api_key:
        raise RuntimeError("Missing AI_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY.")
    return {
        "api_key": api_key,
        "base_url": os.getenv("AI_BASE_URL")
        or os.getenv("DEEPSEEK_BASE_URL")
        or DEFAULT_BASE_URL,
        "model": os.getenv("AI_MODEL") or os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL,
    }


def call_chat_completion(messages: list[dict]) -> str:
    settings = api_settings_from_env()
    url = settings["base_url"].rstrip("/") + "/chat/completions"
    body: dict = {
        "model": settings["model"],
        "messages": messages,
        "stream": False,
        "max_tokens": int(os.getenv("AI_MAX_TOKENS", "1200")),
        "temperature": float(os.getenv("AI_TEMPERATURE", "0.2")),
        "response_format": {"type": "json_object"},
    }
    thinking = os.getenv("AI_THINKING", "disabled")
    if "deepseek.com" in settings["base_url"] or os.getenv("AI_THINKING"):
        body["thinking"] = {"type": thinking}

    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            if not content:
                raise RuntimeError("API returned empty JSON content.")
            return content
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            if exc.code < 500 or attempt == 2:
                raise RuntimeError(f"API request failed: HTTP {exc.code} {details}") from exc
        except urllib.error.URLError as exc:
            if attempt == 2:
                raise RuntimeError(f"API request failed: {exc}") from exc
        time.sleep(2**attempt)

    raise RuntimeError("API request failed after retries.")


def parse_explanation_response(content: str) -> dict:
    data = json.loads(content)
    return normalize_explanation(data)


def normalize_explanation(value: object) -> dict:
    if isinstance(value, dict):
        wrong_options = value.get("wrong_options", [])
        if not isinstance(wrong_options, list):
            wrong_options = []
        normalized_wrong_options = []
        for item in wrong_options:
            if isinstance(item, dict):
                normalized_wrong_options.append(
                    {
                        "option": str(item.get("option", "")).strip(),
                        "reason": str(item.get("reason", "")).strip(),
                    }
                )
            elif item:
                normalized_wrong_options.append({"option": "", "reason": str(item).strip()})

        return {
            "correct_reason": str(value.get("correct_reason", "")).strip(),
            "wrong_options": [
                item for item in normalized_wrong_options if item["option"] or item["reason"]
            ],
            "knowledge_points": _string_list(value.get("knowledge_points", [])),
            "principles": _string_list(value.get("principles", [])),
        }
    return {
        "correct_reason": str(value or "").strip(),
        "wrong_options": [],
        "knowledge_points": [],
        "principles": [],
    }


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value:
        return [str(value).strip()]
    return []


def enrich_questions(
    questions: Iterable[dict],
    client: Callable[[list[dict]], str] = call_chat_completion,
    cache: dict[str, dict] | None = None,
    dry_run: bool = False,
) -> list[dict]:
    cache = cache or {}
    enriched: list[dict] = []
    for question in questions:
        item = dict(question)
        key = question_key(item)
        cached = cache.get(key)
        if cached and cached.get("explanation"):
            item["explanation"] = normalize_explanation(cached["explanation"])
            item["explanation_source"] = cached.get("explanation_source", "cache")
        elif item.get("explanation"):
            item["explanation"] = normalize_explanation(item["explanation"])
            item["explanation_source"] = item.get("explanation_source", "platform")
        elif dry_run:
            item["explanation"] = normalize_explanation(
                {"correct_reason": "待生成：dry-run 模式未调用 AI API。"}
            )
            item["explanation_source"] = "missing"
        else:
            item["explanation"] = parse_explanation_response(client(build_prompt(item)))
            item["explanation_source"] = "ai"
        enriched.append(item)
    return enriched


def update_cache(cache: dict[str, dict], questions: Iterable[dict]) -> dict[str, dict]:
    updated = dict(cache)
    for question in questions:
        if question.get("explanation") and question.get("explanation_source") != "missing":
            updated[question_key(question)] = {
                "explanation": normalize_explanation(question["explanation"]),
                "explanation_source": question.get("explanation_source", "ai"),
            }
    return updated


def render_markdown(questions: list[dict], title: str) -> str:
    lines = [f"# {title}", ""]
    current_course = None
    for index, question in enumerate(questions, 1):
        course = question.get("courseName") or "未命名课程"
        if course != current_course:
            lines.extend([f"## {course}", ""])
            current_course = course
        lines.extend(
            [
                f"### {index}. {question.get('question', '')}",
                "",
                f"**答案：{question.get('answer', '')}**",
                "",
                f"题型：{question.get('type', '')}",
                "",
            ]
        )
        for option in question.get("options", []):
            lines.append(f"- {option}")
        if question.get("options"):
            lines.append("")
        source = question.get("explanation_source", "unknown")
        explanation_lines = render_explanation_markdown(question.get("explanation"))
        lines.extend(
            [
                "**解析**",
                "",
                *explanation_lines,
                f"解析来源：{_source_label(source)}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def render_explanation_markdown(explanation: object) -> list[str]:
    item = normalize_explanation(explanation)
    lines = [
        "**正确答案解析：**",
        item["correct_reason"] or "暂无解析。",
        "",
    ]
    if item["wrong_options"]:
        lines.extend(["**干扰项分析：**", ""])
        for wrong in item["wrong_options"]:
            prefix = f"{wrong['option']}：" if wrong["option"] else ""
            lines.append(f"- {prefix}{wrong['reason']}")
        lines.append("")
    if item["knowledge_points"]:
        lines.extend(["**相关知识点：**", ""])
        lines.extend([f"- {point}" for point in item["knowledge_points"]])
        lines.append("")
    if item["principles"]:
        lines.extend(["**关联原理：**", ""])
        lines.extend([f"- {principle}" for principle in item["principles"]])
        lines.append("")
    return lines


def _source_label(source: str) -> str:
    return {"ai": "AI", "platform": "平台", "cache": "缓存", "missing": "未生成"}.get(
        source, source
    )


def write_docx(questions: list[dict], title: str, output_path: Path) -> None:
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
    except ImportError as exc:
        raise RuntimeError("python-docx is required to write DOCX files.") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.add_heading(title, level=0)
    current_course = None
    for index, question in enumerate(questions, 1):
        course = question.get("courseName") or "未命名课程"
        if course != current_course:
            document.add_heading(course, level=1)
            current_course = course
        question_paragraph = document.add_paragraph()
        question_run = question_paragraph.add_run(f"{index}. {question.get('question', '')}")
        question_run.bold = True
        question_run.font.size = Pt(QUESTION_FONT_SIZE_PT)
        question_run.font.color.rgb = RGBColor(46, 91, 170)
        answer_paragraph = document.add_paragraph()
        answer_run = answer_paragraph.add_run(f"答案：{question.get('answer', '')}")
        answer_run.bold = True
        answer_run.font.size = Pt(CALLOUT_FONT_SIZE_PT)
        answer_run.font.color.rgb = RGBColor(0, 0, 0)
        document.add_paragraph(f"题型：{question.get('type', '')}")
        for option in question.get("options", []):
            document.add_paragraph(option, style="List Bullet")
        add_explanation_docx(document, question.get("explanation"))
        document.add_paragraph(f"解析来源：{_source_label(question.get('explanation_source', 'unknown'))}")
    document.save(output_path)


def add_explanation_docx(document, explanation: object) -> None:
    from docx.shared import Pt, RGBColor

    item = normalize_explanation(explanation)
    add_callout_paragraph(document, "解析")
    add_callout_paragraph(document, "正确答案解析：")
    document.add_paragraph(item["correct_reason"] or "暂无解析。")
    if item["wrong_options"]:
        add_callout_paragraph(document, "干扰项分析：")
        for wrong in item["wrong_options"]:
            prefix = f"{wrong['option']}：" if wrong["option"] else ""
            document.add_paragraph(f"{prefix}{wrong['reason']}", style="List Bullet")
    if item["knowledge_points"]:
        add_callout_paragraph(document, "相关知识点：")
        for point in item["knowledge_points"]:
            document.add_paragraph(point, style="List Bullet")
    if item["principles"]:
        add_callout_paragraph(document, "关联原理：")
        for principle in item["principles"]:
            document.add_paragraph(principle, style="List Bullet")


def add_callout_paragraph(document, text: str) -> None:
    from docx.shared import Pt, RGBColor

    paragraph = document.add_paragraph()
    run = paragraph.add_run(text)
    run.bold = True
    run.font.size = Pt(CALLOUT_FONT_SIZE_PT)
    run.font.color.rgb = RGBColor(0, 0, 0)


def build_outputs(args: argparse.Namespace) -> list[dict]:
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    title = args.title or input_path.name or "学习通作业复习资料"
    cache_path = Path(args.cache) if args.cache else output_dir / "explanations.cache.json"
    load_dotenv(Path.cwd() / ".env")
    if input_path.is_dir():
        load_dotenv(input_path / ".env")

    questions = load_questions(input_path)
    cache = load_cache(cache_path)
    enriched = enrich_questions(questions, cache=cache, dry_run=args.dry_run)

    output_dir.mkdir(parents=True, exist_ok=True)
    save_json(output_dir / "questions.enriched.json", enriched)
    save_json(cache_path, update_cache(cache, enriched))
    (output_dir / f"{title}.md").write_text(
        render_markdown(enriched, title), encoding="utf-8"
    )
    write_docx(enriched, title, output_dir / f"{title}.docx")
    return enriched


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge Chaoxing JSON homework exports and build review DOCX/Markdown."
    )
    parser.add_argument("input", help="JSON file or directory containing JSON exports.")
    parser.add_argument("--output-dir", default="output", help="Output directory.")
    parser.add_argument("--cache", help="Explanation cache JSON path.")
    parser.add_argument("--title", help="Document title and output filename stem.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not call the AI API; mark missing explanations instead.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    enriched = build_outputs(args)
    print(f"Processed {len(enriched)} questions.")


if __name__ == "__main__":
    main()
