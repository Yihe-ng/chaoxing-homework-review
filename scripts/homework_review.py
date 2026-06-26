"""Build review documents from Chaoxing homework exports."""

from __future__ import annotations

import argparse
import base64
import email.utils
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable
from xml.sax.saxutils import escape


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_MAX_TOKENS = 2000
DEFAULT_DOCX_FONT = "Microsoft YaHei"
DEFAULT_API_USER_AGENT = "ChaoxingHomeworkReview/0.1 OpenAI-Compatible-Client"
QUESTION_FONT_SIZE_PT = 13
CALLOUT_FONT_SIZE_PT = 12
TIP_SHADE = "FFF4D6"
MEMORY_ANSWER_SHADE = "E8EEF5"
MEMORY_NOTE_SHADE = "F7F2E8"
MEMORY_ACCENT_COLOR = "5B7DB8"
LINE_COLOR = "000000"


def normalize_question_text(text: str) -> str:
    text = re.sub(r"^\s*\d+[.．、]\s*", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.split(r"\s+[A-Z]\s*[.．、]\s*\S+", text, maxsplit=1)[0]
    text = re.sub(r"\s+[A-Z]\s*[:：].*$", "", text)
    text = re.sub(r"\s+[A-Z]\s*[.．、]\s*$", "", text)
    text = re.sub(r"\s+\d+(?:\.\d+)?\s*分$", "", text)
    return text.strip()


def normalize_option(option: str) -> str:
    option = re.sub(r"\s+", " ", option or "").strip()
    option = re.sub(r"^([A-Z])\s*[.．、]\s*", r"\1. ", option)
    option = re.sub(r"^([A-Z])\. \1\s*[.．、]\s*", r"\1. ", option)
    return option


def normalize_answer(answer: object) -> str:
    text = str(answer or "").strip()
    parts = [part.strip() for part in text.split("###") if part.strip()]
    return "；".join(parts) if parts else text


def format_answer_with_option_text(answer: object, options: list[str]) -> str:
    text = normalize_answer(answer)
    option_map: dict[str, str] = {}
    for option in options:
        normalized = normalize_option(option)
        match = re.match(r"^([A-Z])\.\s*\S+", normalized)
        if match:
            option_map[match.group(1)] = normalized
    if not text or not option_map:
        return text

    normalized_parts = [
        normalize_option(part)
        for part in re.split(r"[；;]\s*", text)
        if part.strip()
    ]
    if normalized_parts and all(
        re.match(r"^[A-Z]\.\s*\S+", part) for part in normalized_parts
    ):
        return "；".join(normalized_parts)

    compact = re.sub(r"[\s；;、,，/]+", "", text).upper()
    if (
        compact
        and re.fullmatch(r"[A-Z]+", compact)
        and all(label in option_map for label in compact)
    ):
        return "；".join(option_map[label] for label in compact)

    labels = [
        part.strip().upper().rstrip(".．、")
        for part in re.split(r"[\s；;、,，/]+", text)
        if part.strip()
    ]
    if labels and all(re.fullmatch(r"[A-Z]", label) and label in option_map for label in labels):
        return "；".join(option_map[label] for label in labels)

    return text


def resolve_answer(question: dict) -> dict:
    visibility = question.get("answer_visibility", "correct_answer_visible")
    correct_answer = normalize_answer(question.get("correct_answer", ""))
    student_answer = normalize_answer(question.get("student_answer", ""))
    exported_answer = normalize_answer(question.get("answer", ""))
    score = _score_value(question.get("score", ""))
    full_score = _full_score_from_type(question.get("type", ""))

    if correct_answer:
        return {
            "answer": correct_answer,
            "trusted": True,
            "source": "correct_answer_visible",
            "needs_review": False,
        }
    if visibility == "correct_answer_visible":
        return {
            "answer": exported_answer,
            "trusted": True,
            "source": "correct_answer_visible",
            "needs_review": False,
        }

    candidate = student_answer or exported_answer
    if candidate and score is not None and full_score is not None and score == full_score:
        return {
            "answer": candidate,
            "trusted": True,
            "source": "inferred_from_full_score",
            "needs_review": True,
        }
    if candidate and score == 0 and "判断题" in str(question.get("type", "")):
        inferred = _opposite_true_false_answer(candidate, question.get("options", []))
        if inferred:
            return {
                "answer": inferred,
                "trusted": True,
                "source": "inferred_from_zero_score_true_false",
                "needs_review": True,
            }

    return {
        "answer": "",
        "trusted": False,
        "source": "answer_unknown",
        "needs_review": True,
    }


def _score_value(value: object) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*分", str(value or ""))
    if not match:
        return None
    return float(match.group(1))


def _full_score_from_type(value: object) -> float | None:
    return _score_value(value)


def _opposite_true_false_answer(answer: str, options: list[str]) -> str:
    normalized = re.sub(r"^[A-Z]\.\s*", "", answer).strip()
    label = answer.strip().upper()
    labels: dict[str, str] = {}
    texts: dict[str, str] = {}
    for option in options:
        match = re.match(r"^([A-Z])\.\s*(.*)$", str(option).strip())
        if not match:
            continue
        option_label, option_text = match.group(1), match.group(2).strip()
        labels[option_label] = option_text
        texts[option_text] = option_label
    if label in labels:
        normalized = labels[label]
    elif normalized in texts:
        label = texts[normalized]

    if normalized in {"对", "正确", "是", "√"}:
        return "错" if any(value == "错" for value in labels.values()) else "错误"
    if normalized in {"错", "错误", "否", "×"}:
        return "对" if any(value == "对" for value in labels.values()) else "正确"
    if label == "A" and labels.get("B"):
        return labels["B"]
    if label == "B" and labels.get("A"):
        return labels["A"]
    return ""


def normalize_question(raw: dict, meta: dict | None = None, source_file: str = "") -> dict:
    meta = meta or {}
    question = dict(raw)
    # TODO: 后续拿到带平台解析的真实学习通样本后，
    # 将 analysis/platform_analysis 映射到 explanation 以便复习资料复用。
    question["courseName"] = question.get("courseName") or meta.get("courseName", "")
    question["homeworkTitle"] = meta.get("homeworkTitle", "")
    if source_file:
        question["sourceFile"] = source_file
    question["question"] = normalize_question_text(question.get("question", ""))
    question["options"] = [
        normalize_option(option) for option in question.get("options", []) if option
    ]
    question["answer"] = normalize_answer(question.get("answer", ""))
    question["images"] = normalize_images(question.get("images", []))
    return question


def question_key(question: dict) -> str:
    resolved = resolve_answer(question)
    payload = {
        "type": question.get("type", ""),
        "question": normalize_question_text(question.get("question", "")),
        "options": [normalize_option(item) for item in question.get("options", [])],
        "answer": resolved["answer"],
    }
    if resolved["source"] != "correct_answer_visible":
        payload["answer_source"] = resolved["source"]
    image_urls = [image["url"] for image in normalize_images(question.get("images", []))]
    if image_urls:
        payload["images"] = image_urls
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_questions(input_path: Path | str | Iterable[Path | str]) -> list[dict]:
    if isinstance(input_path, (str, Path)):
        root = Path(input_path)
        files = sorted(root.rglob("*.json")) if root.is_dir() else [root]
    else:
        files = [Path(item) for item in input_path]
    files = [file_path for file_path in files if is_source_json_file(file_path)]
    files = sorted(files, key=source_file_sort_key)
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


def source_file_sort_key(file_path: Path) -> tuple[int, int, str]:
    chapter = extract_chapter_number(file_path.name)
    if chapter is None:
        return (1, 0, file_path.name)
    return (0, chapter, file_path.name)


def extract_chapter_number(text: str) -> int | None:
    match = re.search(r"第([一二三四五六七八九十百千万两\d]+)章", text)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return int(token)
    return chinese_number_to_int(token)


def chinese_number_to_int(text: str) -> int:
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = 0
    section = 0
    number = 0
    for char in text:
        if char in digits:
            number = digits[char]
        elif char in units:
            unit = units[char]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
    return total + section + number


def is_source_json_file(file_path: Path) -> bool:
    generated_names = {
        "questions.enriched.json",
        "questions.partial.json",
        "explanations.cache.json",
    }
    if file_path.name in generated_names:
        return False
    return True


def apply_limit(questions: list[dict], limit: int | None) -> list[dict]:
    if not limit or limit <= 0:
        return questions
    return questions[:limit]


def log_progress(
    stage: str,
    index: int,
    total: int,
    question: str,
    logger: Callable[[str], None] = print,
) -> None:
    title = re.sub(r"\s+", " ", question or "").strip()
    if len(title) > 48:
        title = title[:45] + "..."
    logger(f"[{index}/{total}] {stage}：{title}")


def load_cache(cache_path: Path | None) -> dict[str, dict]:
    if not cache_path or not cache_path.exists():
        return {}
    return json.loads(cache_path.read_text(encoding="utf-8"))


def save_json(path: Path, data: object) -> None:
    save_json_atomic(path, data)


def save_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(3):
        try:
            temp_path.replace(path)
            return
        except PermissionError:
            if attempt == 2:
                break
            time.sleep(0.5)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        temp_path.unlink(missing_ok=True)
    except OSError:
        pass


def docx_font_name() -> str:
    font_name = os.getenv("DOCX_FONT", "").strip()
    if is_valid_font_name(font_name):
        return font_name
    return DEFAULT_DOCX_FONT


def is_valid_font_name(font_name: str) -> bool:
    if not font_name or len(font_name) > 80:
        return False
    return bool(re.fullmatch(r"[\w\s\-\u4e00-\u9fff]+", font_name, re.UNICODE))


def _http_error_message(code: int) -> str:
    messages = {
        400: "HTTP 400 请求格式有误，请联系开发者",
        401: "HTTP 401 API 密钥无效，请检查 .env 中的 AI_API_KEY",
        402: "HTTP 402 账户余额不足，请检查平台账户余额",
        422: "HTTP 422 参数有误（如模型名称错误），请检查 .env 中的 AI_MODEL",
        429: "HTTP 429 请求太频繁，请稍后重试",
        500: "HTTP 500 服务器内部错误，请稍后重试",
        503: "HTTP 503 服务器繁忙，请稍后重试",
    }
    return messages.get(code, f"HTTP {code} 请求异常，请稍后重试")


def _parse_retry_after(headers) -> int | None:
    """Extract Retry-After seconds from response headers. Returns None if absent."""
    value = headers.get("Retry-After") or headers.get("retry-after")
    if not value:
        return None
    try:
        seconds = int(value)
        return max(0, min(seconds, 120))
    except ValueError:
        try:
            parsed = email.utils.parsedate(value)
            if parsed:
                retry_time = time.mktime(parsed)
                wait = int(retry_time - time.time())
                return max(0, min(wait, 120))
        except (ValueError, TypeError, OverflowError):
            pass
    return None


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


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def ai_vision_enabled() -> bool:
    return env_flag("AI_VISION_ENABLED", False)


def ai_vision_max_images() -> int:
    try:
        return max(0, int(os.getenv("AI_VISION_MAX_IMAGES", "4")))
    except ValueError:
        return 4


def normalize_images(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    images = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, str):
            image = {"url": item}
        elif isinstance(item, dict):
            image = dict(item)
        else:
            continue
        url = str(image.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        images.append(
            {
                "url": url,
                "data_url": str(image.get("data_url", "")).strip(),
                "alt": str(image.get("alt", "")).strip(),
                "title": str(image.get("title", "")).strip(),
                **({"option": str(image.get("option", "")).strip()} if image.get("option") else {}),
                **({"download_error": str(image.get("download_error", "")).strip()} if image.get("download_error") else {}),
            }
        )
    return images


def prompt_images(question: dict) -> list[dict]:
    if not ai_vision_enabled():
        return []
    return normalize_images(question.get("images", []))[:ai_vision_max_images()]


def build_user_content(text: str, images: list[dict]) -> str | list[dict]:
    if not images:
        return text
    content: list[dict] = [{"type": "text", "text": text}]
    for image in images:
        content.append({"type": "image_url", "image_url": {"url": image_payload_url(image)}})
    return content


def image_payload_url(image: dict) -> str:
    return image.get("data_url") or image["url"]


def image_prompt_note(question: dict) -> str:
    images = normalize_images(question.get("images", []))
    if not images:
        return ""
    if not ai_vision_enabled():
        return "\n题目图片：已采集到图片，但 AI_VISION_ENABLED 未开启，本次不会发送图片。"
    limited = images[:ai_vision_max_images()]
    lines = ["", f"题目图片：本次随请求发送 {len(limited)} 张图片。"]
    for index, image in enumerate(limited, 1):
        label = f"选项 {image['option']}" if image.get("option") else "题干"
        alt = f"，说明：{image['alt']}" if image.get("alt") else ""
        source = "，已内嵌图片数据" if image.get("data_url") else "，使用原始图片 URL"
        lines.append(f"{index}. {label}{alt}{source}")
    return "\n".join(lines)


def build_prompt(question: dict) -> list[dict]:
    resolved = resolve_answer(question)
    if not resolved["trusted"]:
        return build_review_prompt(question)
    options = "\n".join(question.get("options", [])) or "无"
    user = f"""题型：{question.get("type", "")}
题目：{question.get("question", "")}
选项：
{options}
已知正确答案：{resolved["answer"]}
答案依据：{_answer_source_label(resolved["source"])}{image_prompt_note(question)}

请生成适合复习背诵的中文解析，并严格输出 json。"""
    images = prompt_images(question)
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
                '"review_tip":"复习抓手：看到哪些关键词或条件时应如何快速判断",'
                '"knowledge_points":["这道题涉及的知识点，需展开说明其含义和复习时要抓住什么"],'
                '"principles":["这道题背后的判断原理，需说明遇到同类题怎么判断"]}。'
                "correct_reason 控制在 80 到 150 字；wrong_options 覆盖明显错误选项；"
                "review_tip 用 1 句话说明考试时如何快速识别答案；"
                "knowledge_points 和 principles 各给 1 到 4 条，每条 50 到 110 字；"
                "不要只写标签或名词短语，要展开说明为什么这个知识点与题目有关，"
                "以及学生复习时应该记住的判断线索。"
                "如果用户消息包含图片，请结合图片内容判断题干、选项、公式或图表。"
            ),
        },
        {"role": "user", "content": build_user_content(user, images)},
    ]


def build_review_prompt(question: dict) -> list[dict]:
    options = "\n".join(question.get("options", [])) or "无"
    student_answer = normalize_answer(
        question.get("student_answer") or question.get("answer", "")
    )
    user = f"""题型：{question.get("type", "")}
题目：{question.get("question", "")}
选项：
{options}
学生答案：{student_answer or "未读取到"}
得分：{question.get("score", "") or "未读取到"}
标准答案未确认：页面未提供老师公布的正确答案，且得分不足以可靠推定标准答案。{image_prompt_note(question)}

请不要把学生答案当作正确答案。请独立分析本题考点，逐项判断各选项是否可能正确。
如能较高置信度判断答案，请给出 model_answer；否则 model_answer 留空。
所有结论都必须标明待人工复核，并严格输出 json。"""
    images = prompt_images(question)
    return [
        {
            "role": "system",
            "content": (
                "你是课程题目复核助手。当前题目没有可靠标准答案，"
                "你的任务是生成复核型解析，而不是标准答案解析。"
                "不要默认相信学生答案，不要把模型倾向答案写成已确认正确答案。"
                "必须只输出合法 json，不要输出 Markdown。json 格式示例："
                '{"correct_reason":"标准答案未确认。请说明本题考点、'
                '学生答案与得分暴露出的风险，以及需要人工核对的关键点",'
                '"model_answer":"模型倾向答案，无法判断则留空",'
                '"confidence":0.0,'
                '"wrong_options":[{"option":"A","reason":"逐项说明该选项可能正确、'
                '可能错误或不确定的理由"}],'
                '"review_tip":"人工复核时应优先核对教材或课件中的哪类表述",'
                '"knowledge_points":["本题涉及的知识点"],'
                '"principles":["同类题判断时可用的原则"]}。'
                "correct_reason 必须明确包含“标准答案未确认”或“待人工复核”。"
            ),
        },
        {"role": "user", "content": build_user_content(user, images)},
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


def api_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": DEFAULT_API_USER_AGENT,
    }


def call_chat_completion(messages: list[dict]) -> str:
    settings = api_settings_from_env()
    url = settings["base_url"].rstrip("/") + "/chat/completions"
    body: dict = {
        "model": settings["model"],
        "messages": messages,
        "stream": False,
        "max_tokens": int(os.getenv("AI_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))),
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
        headers=api_headers(settings["api_key"]),
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
            if exc.code == 429:
                if attempt == 2:
                    raise RuntimeError(
                        f"API 请求失败: {_http_error_message(exc.code)}"
                    ) from exc
                wait = _parse_retry_after(exc.headers) or 30
                time.sleep(wait)
                continue
            if exc.code < 500:
                raise RuntimeError(
                    f"API 请求失败: {_http_error_message(exc.code)}"
                ) from exc
        except urllib.error.URLError as exc:
            if attempt == 2:
                raise RuntimeError(f"API 请求失败: 网络连接错误 ({exc})") from exc
        time.sleep(2**attempt)

    raise RuntimeError("API request failed after retries.")


def parse_explanation_response(content: str) -> dict:
    data = json.loads(content)
    return normalize_explanation(data)


def build_answer_check_prompt(question: dict) -> list[dict]:
    options = "\n".join(question.get("options", [])) or "无"
    user = f"""题型：{question.get("type", "")}
题目：{question.get("question", "")}
选项：
{options}
导出答案：{question.get("answer", "")}{image_prompt_note(question)}

请独立校验导出答案是否合理，并严格输出 json。"""
    images = prompt_images(question)
    return [
        {
            "role": "system",
            "content": (
                "你是答案校验器。请先独立判断题目的合理答案，再和导出答案比较。"
                "不要默认相信导出答案，也不要自动修改答案。必须只输出合法 json，"
                "不要输出 Markdown。json 格式示例："
                '{"provided_answer":"导出答案","model_answer":"你独立判断的答案",'
                '"verdict":"agree|disagree|uncertain",'
                '"confidence":0.0,'
                '"risk_level":"low|medium|high",'
                '"reason":"简要说明为什么一致、不一致或不确定",'
                '"needs_review":false}。'
                "如果题目有歧义、多个选项可能成立、信息不足或你不确定，"
                "verdict 用 uncertain，needs_review 用 true。"
                "如果用户消息包含图片，请结合图片内容校验答案。"
            ),
        },
        {"role": "user", "content": build_user_content(user, images)},
    ]


def parse_answer_check_response(content: str) -> dict:
    return normalize_answer_check(json.loads(content))


def normalize_answer_check(value: object) -> dict:
    if not isinstance(value, dict):
        value = {}
    verdict = str(value.get("verdict", "uncertain")).strip().lower()
    if verdict not in {"agree", "disagree", "uncertain"}:
        verdict = "uncertain"
    risk_level = str(value.get("risk_level", "")).strip().lower()
    if risk_level not in {"low", "medium", "high"}:
        risk_level = {"agree": "low", "disagree": "high"}.get(verdict, "medium")
    try:
        confidence = float(value.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    needs_review = bool(value.get("needs_review", verdict != "agree" or risk_level != "low"))
    return {
        "provided_answer": str(value.get("provided_answer", "")).strip(),
        "model_answer": str(value.get("model_answer", "")).strip(),
        "verdict": verdict,
        "confidence": max(0.0, min(1.0, confidence)),
        "risk_level": risk_level,
        "reason": str(value.get("reason", "")).strip(),
        "needs_review": needs_review,
    }


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
            "model_answer": normalize_answer(value.get("model_answer", "")),
            "confidence": _confidence_value(value.get("confidence")),
            "wrong_options": [
                item for item in normalized_wrong_options if item["option"] or item["reason"]
            ],
            "review_tip": str(value.get("review_tip", "")).strip(),
            "knowledge_points": _string_list(value.get("knowledge_points", [])),
            "principles": _string_list(value.get("principles", [])),
        }
    return {
        "correct_reason": str(value or "").strip(),
        "model_answer": "",
        "confidence": 0.0,
        "wrong_options": [],
        "review_tip": "",
        "knowledge_points": [],
        "principles": [],
    }


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value:
        return [str(value).strip()]
    return []


def _confidence_value(value: object) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def memory_enabled_from_args(args: argparse.Namespace) -> bool:
    if getattr(args, "memory", False):
        return True
    if getattr(args, "no_memory", False):
        return False
    return env_flag("MEMORY_CARDS_ENABLED", False)


def normalize_memory_card(value: object) -> dict:
    if not isinstance(value, dict):
        value = {}
    return {
        "one_liner": str(value.get("one_liner", "")).strip(),
        "plain_explain": str(value.get("plain_explain", "")).strip(),
        "points": _string_list(value.get("points", [])),
        "cue": str(value.get("cue", "")).strip(),
        "trap": str(value.get("trap", "")).strip(),
        "self_test": str(value.get("self_test", "")).strip(),
        "self_test_answer": str(value.get("self_test_answer", "")).strip(),
        "formula": str(value.get("formula", "")).strip(),
        "steps": _string_list(value.get("steps", [])),
    }


def parse_memory_card_response(content: str) -> dict:
    return normalize_memory_card(json.loads(content))


def _is_calculation_like_question(text: str) -> bool:
    formula_patterns = [
        r"\d+\s*[A-Za-z%]*\s*[xX×]\s*\d+",
        r"\d+\s*(?:[+\-*/^=]|>=|<=)\s*\d+",
        r"(?i)\blog\s*2\b",
    ]
    return any(re.search(pattern, text) for pattern in formula_patterns)


def _has_possible_ocr_noise(text: str) -> bool:
    patterns = [
        r"(?<!\d)1/0(?!\d)",
        r"(?<![A-Za-z])I(?=\d)",
        r"(?<=\d)I(?=\d|[KMG]?B|位)",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _number_tokens(text: str) -> set[str]:
    return {match.upper().replace("×", "X") for match in re.findall(r"\d+\s*[KMG]?", text)}


SUPERSCRIPT_TRANS = str.maketrans("0123456789+-()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁽⁾")
SUBSCRIPT_TRANS = str.maketrans("0123456789+-()", "₀₁₂₃₄₅₆₇₈₉₊₋₍₎")


def format_math_text(text: object) -> str:
    formatted = str(text or "")
    formatted = re.sub(
        r"(?i)\blog\s*2\b",
        "log₂",
        formatted,
    )
    formatted = re.sub(
        r"(?i)(\d+\s*[KMGT]?)\s*[x]\s*(\d+)",
        lambda match: f"{match.group(1).replace(' ', '')}×{match.group(2)}",
        formatted,
    )
    formatted = re.sub(
        r"(?<=\d)\s*\*\s*(?=\d)",
        "×",
        formatted,
    )
    formatted = re.sub(
        r"(?<![A-Za-z0-9_])([A-Za-z0-9]+)\^([0-9+\-()]+)",
        lambda match: f"{match.group(1)}{match.group(2).translate(SUPERSCRIPT_TRANS)}",
        formatted,
    )
    formatted = formatted.replace(">=", "≥").replace("<=", "≤").replace("!=", "≠")
    formatted = formatted.replace("->", "→")
    return formatted


def memory_card_quality(question: dict) -> dict:
    card = normalize_memory_card(question.get("memory_card"))
    issues: list[str] = []
    required_fields = {
        "one_liner": "missing_one_liner",
        "plain_explain": "missing_plain_explain",
        "cue": "missing_cue",
        "trap": "missing_trap",
        "self_test": "missing_self_test",
        "self_test_answer": "missing_self_test_answer",
    }
    for field, issue in required_fields.items():
        if not card[field]:
            issues.append(issue)
    if not card["points"]:
        issues.append("missing_points")
    if card["plain_explain"] and len(card["plain_explain"]) < 12:
        issues.append("plain_explain_too_short")
    if card["plain_explain"] and card["plain_explain"] == card["one_liner"]:
        issues.append("plain_explain_repeats_one_liner")
    if card["self_test_answer"] and card["self_test_answer"] == card["self_test"]:
        issues.append("self_test_answer_repeats_question")
    question_text = str(question.get("question", ""))
    if _is_calculation_like_question(question_text):
        if not card["formula"] and not card["steps"]:
            issues.append("calculation_missing_formula_or_steps")
        question_numbers = _number_tokens(question_text)
        self_test_numbers = _number_tokens(card["self_test"])
        if self_test_numbers and not self_test_numbers.issubset(question_numbers):
            issues.append("self_test_introduces_new_numbers")
    suspicious = ["待补充", "无法判断", "不确定", "生成失败"]
    combined = " ".join(
        [
            card["one_liner"],
            card["plain_explain"],
            card["cue"],
            card["trap"],
            card["self_test"],
            card["self_test_answer"],
        ]
    )
    if any(token in combined for token in suspicious):
        issues.append("contains_uncertain_or_failed_text")
    if _has_possible_ocr_noise(question_text):
        issues.append("possible_ocr_noise")
    return {"passed": not issues, "issues": issues}


def format_memory_steps(steps: list[str]) -> str:
    parts = []
    for index, step in enumerate(steps, 1):
        text = str(step).strip()
        if not text:
            continue
        text = format_math_text(text)
        if re.match(r"^\d+[.．、]\s*", text):
            parts.append(text)
        else:
            parts.append(f"{index}. {text}")
    return "；".join(parts)


def build_memory_card_prompt(question: dict) -> list[dict]:
    resolved = resolve_answer(question)
    options = "\n".join(question.get("options", [])) or "无"
    explanation = normalize_explanation(question.get("explanation"))
    answer_line = (
        f"可信答案：{resolved['answer']}\n答案依据：{_answer_source_label(resolved['source'])}"
        if resolved["trusted"]
        else (
            "可信答案：未确认\n"
            f"我的答案：{normalize_answer(question.get('student_answer') or question.get('answer', '')) or '未读取到'}\n"
            f"得分：{question.get('score', '') or '未读取到'}"
        )
    )
    user = f"""题型：{question.get("type", "")}
题目：{question.get("question", "")}
选项：
{options}
{answer_line}

已有解析摘要：{explanation.get("correct_reason", "")}
已有知识点：{"；".join(explanation.get("knowledge_points", []))}
已有判断原则：{"；".join(explanation.get("principles", []))}

请生成考前快速刷背用的速记卡，并严格输出 json。{image_prompt_note(question)}"""
    images = prompt_images(question)
    return [
        {
            "role": "system",
            "content": (
                "你是考前刷背卡片生成器。请把完整解析压缩成短、准、可检索的记忆卡。"
                "必须只输出合法 json，不要输出 Markdown。json 格式："
                '{"one_liner":"不超过20字的一句话速记",'
                '"plain_explain":"一句给没学过的人看的白话解释，必须解释术语，不能只复述题干",'
                '"points":["1到3个考点关键词"],'
                '"cue":"看到什么关键词或结构 -> 怎么判断",'
                '"trap":"最容易误判的点",'
                '"self_test":"闭卷自测问题",'
                '"self_test_answer":"自测题的参考答案，必须能直接回答 self_test",'
                '"formula":"公式或固定换算，没有则留空",'
                '"steps":["计算题或流程题的步骤，没有则为空数组"]}。'
                "概念类题优先写术语边界、包含关系和排除干扰；"
                "计算题或流程题优先写公式、固定结论、单位换算和步骤模板；"
                "理论辨析题优先写关键词触发、限定词、绝对化表述和易混概念。"
                "plain_explain 要面向零基础，说明概念是什么；"
                "self_test 默认围绕本题核心结论提问，不要改题目数字另造新题；"
                "self_test_answer 必须给出答案，不能留空。"
                "如果可信答案未确认，one_liner 必须提示“待复核”，不要把学生答案写成正确答案。"
            ),
        },
        {"role": "user", "content": build_user_content(user, images)},
    ]


def enrich_memory_cards(
    questions: Iterable[dict],
    client: Callable[[list[dict]], str] = call_chat_completion,
    cache: dict[str, dict] | None = None,
    dry_run: bool = False,
    cache_writer: Callable[[dict[str, dict], list[dict]], None] | None = None,
    logger: Callable[[str], None] = print,
) -> list[dict]:
    cache = cache or {}
    enriched: list[dict] = []
    question_list = list(questions)
    total = len(question_list)
    try:
        for index, question in enumerate(question_list, 1):
            item = dict(question)
            key = question_key(item)
            cached = cache.get(key, {})
            if item.get("memory_card"):
                log_progress("使用原速记", index, total, item.get("question", ""), logger)
                item["memory_card"] = normalize_memory_card(item["memory_card"])
                item["memory_card_source"] = item.get("memory_card_source", "existing")
                item["memory_card_quality"] = memory_card_quality(item)
            elif cached.get("memory_card") and cached.get("memory_card_source") != "failed":
                log_progress("使用速记缓存", index, total, item.get("question", ""), logger)
                item["memory_card"] = normalize_memory_card(cached["memory_card"])
                item["cached_memory_card_source"] = cached.get("memory_card_source", "unknown")
                item["memory_card_source"] = "cache"
                item["memory_card_quality"] = memory_card_quality(item)
            elif dry_run:
                log_progress("速记 dry-run", index, total, item.get("question", ""), logger)
                item["memory_card"] = normalize_memory_card(
                    {"one_liner": "待生成：dry-run 模式未调用 AI API。"}
                )
                item["memory_card_source"] = "missing"
                item["memory_card_quality"] = memory_card_quality(item)
            else:
                log_progress("生成速记", index, total, item.get("question", ""), logger)
                try:
                    item["memory_card"] = parse_memory_card_response(
                        client(build_memory_card_prompt(item))
                    )
                    item["memory_card_source"] = (
                        "ai" if resolve_answer(item)["trusted"] else "ai_review"
                    )
                    item["memory_card_quality"] = memory_card_quality(item)
                    time.sleep(0.3)
                except Exception as exc:
                    item["memory_card"] = normalize_memory_card(
                        {
                            "one_liner": "速记生成失败，请查看 processing_error 后重试。",
                            "trap": "本题需要人工补充速记。",
                        }
                    )
                    item["memory_card_source"] = "failed"
                    item["memory_card_quality"] = memory_card_quality(item)
                    item["processing_error"] = (
                        f"{item.get('processing_error', '')}\n速记生成失败：{exc}"
                    ).strip()
                    log_progress("速记失败", index, total, item.get("question", ""), logger)
            enriched.append(item)
            if cache_writer:
                cache = update_cache(cache, [item])
                cache_writer(cache, enriched)
    except KeyboardInterrupt:
        logger("\n用户中断，正在保存已生成的速记卡...")
        if cache_writer:
            cache = update_cache(cache, enriched)
            cache_writer(cache, enriched)
        logger(f"已保存 {len(enriched)} 题速记卡，重新运行可继续补全。")
    return enriched


def enrich_questions(
    questions: Iterable[dict],
    client: Callable[[list[dict]], str] = call_chat_completion,
    cache: dict[str, dict] | None = None,
    dry_run: bool = False,
    verify_answers: bool = False,
    cache_writer: Callable[[dict[str, dict], list[dict]], None] | None = None,
    logger: Callable[[str], None] = print,
    on_consecutive_failures: Callable[[int, list[dict]], bool] | None = None,
) -> list[dict]:
    cache = cache or {}
    enriched: list[dict] = []
    question_list = list(questions)
    total = len(question_list)
    consecutive_failures = 0
    failed_batch: list[dict] = []
    try:
        for index, question in enumerate(question_list, 1):
            item = dict(question)
            key = question_key(item)
            cached = cache.get(key)
            if cached and cached.get("explanation") and cached.get("explanation_source") != "failed":
                log_progress("使用缓存", index, total, item.get("question", ""), logger)
                item["explanation"] = normalize_explanation(cached["explanation"])
                item["cached_explanation_source"] = cached.get("explanation_source", "unknown")
                item["explanation_source"] = "cache"
                if cached.get("answer_check"):
                    item["answer_check"] = normalize_answer_check(cached["answer_check"])
                consecutive_failures = 0
            elif item.get("explanation"):
                log_progress("使用原解析", index, total, item.get("question", ""), logger)
                item["explanation"] = normalize_explanation(item["explanation"])
                item["explanation_source"] = item.get("explanation_source", "platform")
                consecutive_failures = 0
            elif dry_run:
                log_progress("dry-run 占位", index, total, item.get("question", ""), logger)
                item["explanation"] = normalize_explanation(
                    {"correct_reason": "待生成：dry-run 模式未调用 AI API。"}
                )
                item["explanation_source"] = "missing"
                consecutive_failures = 0
            else:
                log_progress("生成解析", index, total, item.get("question", ""), logger)
                try:
                    resolved = resolve_answer(item)
                    item["explanation"] = parse_explanation_response(client(build_prompt(item)))
                    item["explanation_source"] = "ai" if resolved["trusted"] else "ai_review"
                    consecutive_failures = 0
                    time.sleep(0.3)
                except Exception as exc:
                    item["explanation"] = normalize_explanation(
                        {
                            "correct_reason": (
                                "生成解析失败。请查看 processing_error 字段后重试，"
                                "或人工补充本题解析。"
                            )
                        }
                    )
                    item["explanation_source"] = "failed"
                    item["processing_error"] = str(exc)
                    consecutive_failures += 1
                    failed_batch.append(item)
                    log_progress("解析失败", index, total, item.get("question", ""), logger)
                    if on_consecutive_failures and consecutive_failures >= 10:
                        if not on_consecutive_failures(consecutive_failures, list(failed_batch)):
                            logger("已停止解析，已成功部分可通过缓存复用。")
                            break
                        # 用户选择继续 — 从 enriched 弹出失败的题目并逐一重试
                        retry_start = index - len(failed_batch) + 1
                        for _ in failed_batch:
                            enriched.pop()
                        retry_items = list(failed_batch)
                        consecutive_failures = 0
                        failed_batch = []
                        for ri, retry_item in enumerate(retry_items):
                            retry_index = retry_start + ri
                            log_progress("重试解析", retry_index, total, retry_item.get("question", ""), logger)
                            try:
                                resolved = resolve_answer(retry_item)
                                retry_item["explanation"] = parse_explanation_response(
                                    client(build_prompt(retry_item))
                                )
                                retry_item["explanation_source"] = (
                                    "ai" if resolved["trusted"] else "ai_review"
                                )
                                consecutive_failures = 0
                                time.sleep(0.3)
                            except Exception as exc2:
                                retry_item["explanation"] = normalize_explanation(
                                    {
                                        "correct_reason": (
                                            "生成解析失败。请查看 processing_error 字段后重试，"
                                            "或人工补充本题解析。"
                                        )
                                    }
                                )
                                retry_item["explanation_source"] = "failed"
                                retry_item["processing_error"] = str(exc2)
                                consecutive_failures += 1
                                failed_batch.append(retry_item)
                                log_progress(
                                    "重试失败", retry_index, total, retry_item.get("question", ""), logger
                                )
                            enriched.append(retry_item)
                            if cache_writer:
                                cache = update_cache(cache, [retry_item])
                                cache_writer(cache, enriched)
            if verify_answers and not item.get("answer_check") and item.get("explanation_source") != "failed":
                log_progress("答案校验", index, total, item.get("question", ""), logger)
                try:
                    item["answer_check"] = parse_answer_check_response(
                        client(build_answer_check_prompt(item))
                    )
                    time.sleep(0.3)
                except Exception as exc:
                    item["answer_check"] = normalize_answer_check(
                        {
                            "provided_answer": item.get("answer", ""),
                            "model_answer": "",
                            "verdict": "uncertain",
                            "confidence": 0,
                            "risk_level": "medium",
                            "reason": f"答案校验失败：{exc}",
                            "needs_review": True,
                        }
                    )
                    item["processing_error"] = (
                        f"{item.get('processing_error', '')}\n答案校验失败：{exc}"
                    ).strip()
                    log_progress("校验失败", index, total, item.get("question", ""), logger)
            enriched.append(item)
            if cache_writer:
                cache = update_cache(cache, [item])
                cache_writer(cache, enriched)
    except KeyboardInterrupt:
        logger("\n用户中断，正在保存已处理的结果...")
        if cache_writer:
            cache = update_cache(cache, enriched)
            cache_writer(cache, enriched)
        logger(f"已保存 {len(enriched)} 题的处理结果，重新运行命令可继续处理剩余题目。")
    return enriched


def update_cache(cache: dict[str, dict], questions: Iterable[dict]) -> dict[str, dict]:
    updated = dict(cache)
    for question in questions:
        key = question_key(question)
        cached_question = dict(updated.get(key, {}))
        if question.get("explanation") and question.get("explanation_source") not in ("missing", "failed"):
            source = question.get("explanation_source", "ai")
            if source == "cache":
                source = question.get("cached_explanation_source", "ai")
            cached_question["explanation"] = normalize_explanation(question["explanation"])
            cached_question["explanation_source"] = source
            if question.get("answer_check"):
                cached_question["answer_check"] = normalize_answer_check(question["answer_check"])
        if question.get("memory_card") and question.get("memory_card_source") not in (
            "missing",
            "failed",
        ):
            source = question.get("memory_card_source", "ai")
            if source == "cache":
                source = question.get("cached_memory_card_source", "ai")
            cached_question["memory_card"] = normalize_memory_card(question["memory_card"])
            cached_question["memory_card_source"] = source
        if cached_question:
            updated[key] = cached_question
    return updated


def build_run_summary(questions: list[dict]) -> dict[str, int]:
    summary = {
        "total": len(questions),
        "cache": 0,
        "ai": 0,
        "platform": 0,
        "missing": 0,
        "failed": 0,
        "review_needed": 0,
    }
    for question in questions:
        source = question.get("explanation_source", "missing")
        if source in summary:
            summary[source] += 1
        if question.get("answer_check") and normalize_answer_check(question["answer_check"])[
            "needs_review"
        ]:
            summary["review_needed"] += 1
    return summary


def print_run_summary(
    summary: dict[str, int],
    output_dir: Path,
    title: str,
    *,
    docx_failed: bool = False,
    review_needed_path: Path | None = None,
) -> None:
    print("处理汇总：", flush=True)
    print(f"- 总题数：{summary['total']}", flush=True)
    print(f"- 使用缓存：{summary['cache']}", flush=True)
    print(f"- 新生成解析：{summary['ai']}", flush=True)
    print(f"- 处理失败：{summary['failed']}", flush=True)
    print(f"- 需复核：{summary['review_needed']}", flush=True)
    if docx_failed:
        print("- Word：⚠ 写入失败（文件被占用）", flush=True)
    else:
        print(f"- Word：{output_dir / f'{title}.docx'}", flush=True)
    print(f"- Markdown：{output_dir / f'{title}.md'}", flush=True)
    print(f"- 复核清单：{review_needed_path or output_dir / 'review-needed.md'}", flush=True)
    if summary.get("failed", 0) > 0:
        print(
            f"> {summary['failed']} 题未生成解析（已成功的 {summary['total'] - summary['failed']} 题不受影响）。"
            "排查问题后重新运行相同命令即可自动补全，已成功题目会跳过，不会重复调用 API。",
            flush=True,
        )
    if docx_failed:
        print()
        print("═" * 48, flush=True)
        print("⚠  Word 文件未能写入，请关闭 Word / WPS 中打开的该文件后重新运行。", flush=True)
        print("   Markdown 和 JSON 已正常保存。", flush=True)
        print("═" * 48, flush=True)


def render_markdown(questions: list[dict], title: str) -> str:
    lines = [f"# {title}", ""]
    current_course = None
    for index, question in enumerate(questions, 1):
        course = question.get("courseName") or "未命名课程"
        if course != current_course:
            lines.extend([f"## {course}", ""])
            current_course = course
        resolved = resolve_answer(question)
        answer_lines = [f"> **答案：{resolved['answer'] or '未确认'}**"]
        if not resolved["trusted"]:
            student_answer = normalize_answer(
                question.get("student_answer") or question.get("answer", "")
            )
            if student_answer:
                answer_lines.append(f"> 我的答案：{student_answer}")
            if question.get("score"):
                answer_lines.append(f"> 得分：{question.get('score')}")
            model_answer = normalize_explanation(question.get("explanation")).get(
                "model_answer", ""
            )
            if model_answer:
                answer_lines.append(f"> 模型倾向答案：{model_answer}（待复核）")
        answer_lines.append(f"> 题型：{question.get('type', '')}")
        lines.extend(
            [
                f"### {index}. {question.get('question', '')}",
                "",
                *answer_lines,
                "",
            ]
        )
        for option in question.get("options", []):
            lines.append(
                f"- {format_option_markdown(option, resolved['answer'] if resolved['trusted'] else '')}"
            )
        if question.get("options"):
            lines.append("")

        lines.extend(render_question_images_markdown(question))
        source_label = explanation_source_label(question)

        explanation_lines = render_explanation_markdown(question.get("explanation"))
        answer_check_lines = render_answer_check_markdown(question.get("answer_check"))
        answer_source_lines = render_answer_source_markdown(question)
        lines.extend(
            [
                "**解析**",
                "",
                *answer_source_lines,
                *answer_check_lines,
                *explanation_lines,
                f"解析来源：{source_label}",
                "",
                "---",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def render_memory_markdown(questions: list[dict], title: str) -> str:
    lines = [f"# {title}", ""]
    current_course = None
    current_homework = None
    for index, question in enumerate(questions, 1):
        course = question.get("courseName") or "未命名课程"
        if course != current_course:
            lines.extend([f"## {course}", ""])
            current_course = course
            current_homework = None
        homework_title = question.get("homeworkTitle", "")
        if homework_title and homework_title != current_homework:
            lines.extend([f"## {homework_title}", ""])
            current_homework = homework_title
        resolved = resolve_answer(question)
        card = normalize_memory_card(question.get("memory_card"))
        lines.extend([f"### {index}. {question.get('question', '')}", ""])
        if resolved["trusted"]:
            answer_text = format_answer_with_option_text(
                resolved["answer"], question.get("options", [])
            )
            lines.append(f"> **答案：{format_math_text(answer_text)}**")
            if resolved["source"] != "correct_answer_visible":
                lines.append(f"> 来源：{_answer_source_label(resolved['source'])}")
        else:
            student_answer = normalize_answer(
                question.get("student_answer") or question.get("answer", "")
            )
            lines.append("> **答案：未确认**")
            if student_answer:
                student_answer_text = format_answer_with_option_text(
                    student_answer, question.get("options", [])
                )
                lines.append(f"> 我的答案：{format_math_text(student_answer_text)}")
            if question.get("score"):
                lines.append(f"> 得分：{question.get('score')}")
        lines.append("")
        if card["one_liner"]:
            lines.append(f"- **速记：** {format_math_text(card['one_liner'])}")
        if card["plain_explain"]:
            lines.append(f"- **白话：** {format_math_text(card['plain_explain'])}")
        if card["points"]:
            lines.append(f"- **考点：** {format_math_text('；'.join(card['points']))}")
        if card["formula"]:
            lines.append(f"- **公式：** {format_math_text(card['formula'])}")
        if card["steps"]:
            lines.append(f"- **步骤：** {format_memory_steps(card['steps'])}")
        if card["cue"]:
            lines.append(f"- **抓手：** {format_math_text(card['cue'])}")
        if card["trap"]:
            lines.append(f"- **易错：** {format_math_text(card['trap'])}")
        if card["self_test"]:
            lines.append(f"- **自测：** {format_math_text(card['self_test'])}")
        if card["self_test_answer"]:
            lines.append(f"- **自测答案：** {format_math_text(card['self_test_answer'])}")
        quality = question.get("memory_card_quality")
        if quality and not quality.get("passed", True):
            lines.append(f"- **质量提示：** {'；'.join(quality.get('issues', []))}")
        lines.extend(["", "---", ""])
    return "\n".join(lines).strip() + "\n"


def render_answer_check_markdown(answer_check: object) -> list[str]:
    if not answer_check:
        return []
    item = normalize_answer_check(answer_check)
    if not item["needs_review"] and item["risk_level"] == "low":
        return []
    return [
        "**答案可能需要复核**",
        "这道题的导出答案与模型校验结果存在差异或不确定，详见对应的复核清单。",
        "",
    ]


def render_answer_source_markdown(question: dict) -> list[str]:
    resolved = resolve_answer(question)
    if resolved["source"] == "correct_answer_visible":
        return []
    if resolved["trusted"]:
        return [
            "**答案来源需要留意**",
            f"这道题未在页面中读取到标准正确答案，当前答案为{_answer_source_label(resolved['source'])}，详见对应的复核清单。",
            "",
        ]
    return [
        "**答案来源需要留意**",
        "这道题未在页面中读取到可靠标准答案，正文不把我的答案当作正确答案，详见对应的复核清单。",
        "",
    ]


def render_question_images_markdown(question: dict) -> list[str]:
    images = normalize_images(question.get("images", []))
    if not images:
        return []
    lines = ["**题目图片：**", ""]
    for index, image in enumerate(images, 1):
        label = f"选项 {image['option']}" if image.get("option") else "题干"
        alt = image.get("alt") or image.get("title") or label
        src = image_payload_url(image)
        lines.extend([f"**{index}. {label}：**", f"![{escape_markdown_alt(alt)}]({src})", ""])
    lines.append("")
    return lines


def escape_markdown_alt(text: str) -> str:
    return re.sub(r"[\[\]\n\r]", " ", text).strip() or "题目图片"


def render_explanation_markdown(explanation: object) -> list[str]:
    item = normalize_explanation(explanation)
    lines = [
        "**为什么选：**",
        item["correct_reason"] or "暂无解析。",
        "",
    ]
    if item.get("model_answer"):
        lines.extend(
            [
                "**模型倾向答案（待复核）：**",
                f"{item['model_answer']}（置信度：{item['confidence']:.2f}）",
                "",
            ]
        )
    if item["wrong_options"]:
        lines.extend(["**为什么不选：**", ""])
        for wrong in item["wrong_options"]:
            prefix = f"{wrong['option']}：" if wrong["option"] else ""
            lines.append(f"- {prefix}{wrong['reason']}")
        lines.append("")
    if item["review_tip"]:
        lines.extend(["**复习抓手：**", f"> {item['review_tip']}", ""])
    if item["knowledge_points"]:
        lines.extend(["**知识补充：**", ""])
        lines.extend([f"- {point}" for point in item["knowledge_points"]])
        lines.append("")
    if item["principles"]:
        lines.extend(["**同类题判断法：**", ""])
        lines.extend([f"- {principle}" for principle in item["principles"]])
        lines.append("")
    return lines


def render_review_needed_markdown(questions: list[dict], title: str) -> str:
    flagged = [
        question
        for question in questions
        if _needs_review(question)
    ]
    lines = [f"# {title}", "", f"需复核题目数：{len(flagged)}", ""]
    for index, question in enumerate(flagged, 1):
        check = normalize_answer_check(question.get("answer_check", {}))
        resolved = resolve_answer(question)
        student_answer = normalize_answer(
            question.get("student_answer") or question.get("answer", "")
        )
        homework_title = question.get("homeworkTitle", "")
        chapter_part = _extract_chapter_label(homework_title)
        q_index = question.get("index")
        source_label = f"{chapter_part} 第{q_index}题" if chapter_part and q_index else homework_title
        lines.extend(
            [
                f"## {index}. {question.get('question', '')}",
                "",
                f"课程：{question.get('courseName', '未命名课程')}",
                "",
                f"来源：{source_label}",
                "",
                f"题型：{question.get('type', '未知')}",
                "",
            ]
        )
        if question.get("options"):
            lines.extend(["选项：", ""])
            lines.extend([f"- {option}" for option in question.get("options", [])])
            lines.append("")
        lines.extend(
            [
                f"解析用答案：{resolved['answer'] or '未确认'}",
                "",
                f"我的答案：{student_answer or '未读取到'}",
                "",
                f"得分：{question.get('score', '') or '未读取到'}",
                "",
                f"答案来源：{_answer_source_label(resolved['source'])}",
                "",
                f"模型判断：{check['model_answer'] or '未提供'}",
                "",
                f"判断状态：{check['verdict']}",
                "",
                f"风险等级：{check['risk_level']}",
                "",
                f"置信度：{check['confidence']:.2f}",
                "",
                f"理由：{check['reason'] or '未提供'}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _extract_chapter_label(homework_title: str) -> str:
    """从作业标题（如"第9章作业"）中提取章节标签（如"第9章"）。"""
    match = re.search(r"(第[^章]+章)", homework_title)
    return match.group(1) if match else homework_title


def _answer_source_label(visibility: str) -> str:
    """将 answer_visibility 内部字段转为用户友好的显示标签。"""
    mapping = {
        "correct_answer_visible": "学习通导出答案",
        "inferred_from_full_score": "满分推定答案",
        "inferred_from_zero_score_true_false": "由判断题 0 分反推",
        "answer_unknown": "未确认",
    }
    return mapping.get(visibility, visibility)


def _needs_review(question: dict) -> bool:
    if resolve_answer(question)["needs_review"]:
        return True
    if question.get("answer_check"):
        return normalize_answer_check(question["answer_check"])["needs_review"]
    return False


def format_option_markdown(option: str, answer: str) -> str:
    if is_correct_option(option, answer):
        return f"**{option}** ✅"
    return option


def is_correct_option(option: str, answer: str) -> bool:
    label_match = re.match(r"^([A-Z])\.\s*(.*)$", option.strip())
    option_label = label_match.group(1) if label_match else ""
    option_text = re.sub(r"^[A-Z]\.\s*", "", option).strip()
    answer_parts = [
        re.sub(r"^[A-Z]\.\s*", "", part.strip())
        for part in re.split(r"[；;,，、\s]+", str(answer))
        if part.strip()
    ]
    return any(part == option_label or part == option_text for part in answer_parts)


def ai_model_label() -> str:
    return os.getenv("AI_MODEL") or os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL


def explanation_source_label(question: dict) -> str:
    source = question.get("explanation_source", "unknown")
    if source == "ai":
        return ai_model_label()
    if source == "cache":
        cached_source = question.get("cached_explanation_source", "")
        if cached_source == "ai":
            return f"{ai_model_label()}（已缓存）"
        if cached_source:
            return f"{_source_label(cached_source)}（已缓存）"
    return _source_label(str(source))


def _source_label(source: str) -> str:
    return {
        "platform": "平台",
        "cache": "缓存",
        "missing": "未生成",
        "ai_review": "模型复核（待人工确认）",
    }.get(source, source)


def write_docx(questions: list[dict], title: str, output_path: Path) -> None:
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
    except ImportError as exc:
        raise RuntimeError("python-docx is required to write DOCX files.") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    configure_document_styles(document)
    _add_heading(document, title, 0)
    current_course = None
    current_chapter = None
    for index, question in enumerate(questions, 1):
        course = question.get("courseName") or "未命名课程"
        chapter = question.get("homeworkTitle", "")
        if course != current_course:
            _add_heading(document, course, 1)
            current_course = course
            current_chapter = None
        if chapter and chapter != current_chapter:
            _add_heading(document, chapter, 2)
            current_chapter = chapter
        question_paragraph = document.add_paragraph()
        question_run = question_paragraph.add_run(f"{index}. {question.get('question', '')}")
        question_run.bold = True
        question_run.font.size = Pt(QUESTION_FONT_SIZE_PT)
        question_run.font.color.rgb = RGBColor(46, 91, 170)
        resolved = resolve_answer(question)
        answer_paragraph = document.add_paragraph()
        answer_run = answer_paragraph.add_run(f"答案：{resolved['answer'] or '未确认'}")
        answer_run.bold = True
        answer_run.font.size = Pt(CALLOUT_FONT_SIZE_PT)
        answer_run.font.color.rgb = RGBColor(0, 0, 0)
        if not resolved["trusted"]:
            student_answer = normalize_answer(
                question.get("student_answer") or question.get("answer", "")
            )
            if student_answer:
                answer_paragraph.add_run(f"\n我的答案：{student_answer}")
            if question.get("score"):
                answer_paragraph.add_run(f"\n得分：{question.get('score')}")
            model_answer = normalize_explanation(question.get("explanation")).get(
                "model_answer", ""
            )
            if model_answer:
                answer_paragraph.add_run(f"\n模型倾向答案：{model_answer}（待复核）")
        answer_paragraph.add_run(f"\n题型：{question.get('type', '')}")
        for option in question.get("options", []):
            paragraph = document.add_paragraph(style="List Bullet")
            run = paragraph.add_run(option)
            if resolved["trusted"] and is_correct_option(option, resolved["answer"]):
                run.bold = True
                run.font.color.rgb = RGBColor(34, 139, 34)
                paragraph.add_run("  ✅")
        add_question_images_docx(document, question)
        add_answer_source_docx(document, question)
        add_answer_check_docx(document, question.get("answer_check"))
        add_explanation_docx(document, question.get("explanation"))
        document.add_paragraph(f"解析来源：{explanation_source_label(question)}")
        add_separator(document)
    document.save(str(output_path))


def write_memory_docx(questions: list[dict], title: str, output_path: Path) -> None:
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
    except ImportError as exc:
        raise RuntimeError("python-docx is required to write DOCX files.") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    configure_document_styles(document)
    _add_heading(document, title, 0)
    current_course = None
    current_chapter = None
    for index, question in enumerate(questions, 1):
        course = question.get("courseName") or "未命名课程"
        chapter = question.get("homeworkTitle", "")
        if course != current_course:
            _add_heading(document, course, 1)
            current_course = course
            current_chapter = None
        if chapter and chapter != current_chapter:
            _add_heading(document, chapter, 2)
            current_chapter = chapter

        question_paragraph = document.add_paragraph()
        question_paragraph.paragraph_format.space_before = Pt(14)
        question_paragraph.paragraph_format.space_after = Pt(8)
        question_paragraph.paragraph_format.line_spacing = 1.28
        question_run = question_paragraph.add_run(f"{index}. {question.get('question', '')}")
        question_run.bold = True
        question_run.font.size = Pt(12.5)
        question_run.font.color.rgb = RGBColor(31, 77, 120)

        for line in _memory_answer_lines(question):
            add_memory_answer_paragraph(document, line)

        card = normalize_memory_card(question.get("memory_card"))
        memory_fields = [
            ("速记", card["one_liner"], True, None),
            ("白话", card["plain_explain"], False, None),
            ("考点", "；".join(card["points"]), False, None),
            ("公式", card["formula"], False, None),
            ("步骤", format_memory_steps(card["steps"]) if card["steps"] else "", False, None),
            ("抓手", card["cue"], False, None),
            ("易错", card["trap"], False, None),
            ("自测", card["self_test"], False, None),
            ("自测答案", card["self_test_answer"], False, None),
        ]
        quality = question.get("memory_card_quality")
        if quality and not quality.get("passed", True):
            memory_fields.append(
                ("质量提示", "；".join(quality.get("issues", [])), False, MEMORY_NOTE_SHADE)
            )
        for label, value, bold_value, fill in memory_fields:
            add_memory_field_paragraph(
                document,
                label,
                value,
                bold_value=bold_value,
                fill=fill,
            )
        add_separator(document)
    document.save(str(output_path))


def _memory_answer_lines(question: dict) -> list[str]:
    resolved = resolve_answer(question)
    if resolved["trusted"]:
        answer_text = format_answer_with_option_text(
            resolved["answer"], question.get("options", [])
        )
        lines = [f"答案：{format_math_text(answer_text)}"]
        if resolved["source"] != "correct_answer_visible":
            lines.append(f"来源：{_answer_source_label(resolved['source'])}")
        return lines
    lines = ["答案：未确认"]
    student_answer = normalize_answer(question.get("student_answer") or question.get("answer", ""))
    if student_answer:
        student_answer_text = format_answer_with_option_text(
            student_answer, question.get("options", [])
        )
        lines.append(f"我的答案：{format_math_text(student_answer_text)}")
    if question.get("score"):
        lines.append(f"得分：{question.get('score')}")
    return lines


def configure_document_styles(document) -> None:
    from docx.shared import Pt
    from docx.oxml.ns import qn

    font_name = docx_font_name()
    normal = document.styles["Normal"]
    normal.font.name = font_name
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.line_spacing = 1.15
    for style_name in ("Title", "Heading 1", "Heading 2", "Heading 3"):
        try:
            style = document.styles[style_name]
            style.font.name = font_name
            style._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
        except KeyError:
            pass


def _add_heading(document, text: str, level: int):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    heading = document.add_heading(text, level=level)
    for run in heading.runs:
        run.font.name = docx_font_name()
        run._element.rPr.rFonts.set(qn("w:eastAsia"), docx_font_name())
    pPr = heading._p.get_or_add_pPr()
    outline = OxmlElement("w:outlineLvl")
    outline.set(qn("w:val"), str(level - 1) if level > 0 else "0")
    pPr.append(outline)
    return heading


def add_answer_check_docx(document, answer_check: object) -> None:
    if not answer_check:
        return
    item = normalize_answer_check(answer_check)
    if not item["needs_review"] and item["risk_level"] == "low":
        return
    add_callout_paragraph(document, "答案可能需要复核")
    add_body_paragraph(document, "这道题的导出答案与模型校验结果存在差异或不确定，详见对应的复核清单。")


def add_answer_source_docx(document, question: dict) -> None:
    resolved = resolve_answer(question)
    if resolved["source"] == "correct_answer_visible":
        return
    add_callout_paragraph(document, "答案来源需要留意")
    if resolved["trusted"]:
        add_body_paragraph(
            document,
            f"未在页面中读取到标准正确答案，当前答案为{_answer_source_label(resolved['source'])}。",
        )
    else:
        add_body_paragraph(
            document,
            "未读取到可靠标准答案，正文不把我的答案当作正确答案，本题需要人工复核。",
        )


def add_question_images_docx(document, question: dict) -> None:
    from docx.shared import Inches

    images = normalize_images(question.get("images", []))
    if not images:
        return
    add_callout_paragraph(document, "题目图片：")
    for index, image in enumerate(images, 1):
        label = f"选项 {image['option']}" if image.get("option") else "题干"
        caption = image.get("alt") or image.get("title") or label
        add_body_paragraph(document, f"{index}. {label}：{caption}")
        if image.get("data_url"):
            try:
                document.add_picture(BytesIO(decode_data_url(image["data_url"])), width=Inches(5.3))
            except Exception:
                add_body_paragraph(document, f"图片写入失败：{image.get('url', '')}")
        elif image.get("url"):
            add_body_paragraph(document, f"图片链接：{image['url']}")


def decode_data_url(value: str) -> bytes:
    match = re.match(r"^data:image/[^;]+;base64,(.+)$", value or "", re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError("不是有效的图片 data URL")
    return base64.b64decode(match.group(1), validate=True)


def add_explanation_docx(document, explanation: object) -> None:
    item = normalize_explanation(explanation)
    add_callout_paragraph(document, "解析")
    add_callout_paragraph(document, "为什么选：")
    add_body_paragraph(document, item["correct_reason"] or "暂无解析。")
    if item["wrong_options"]:
        add_callout_paragraph(document, "为什么不选：")
        for wrong in item["wrong_options"]:
            prefix = f"{wrong['option']}：" if wrong["option"] else ""
            add_list_paragraph(document, f"{prefix}{wrong['reason']}")
    if item["review_tip"]:
        add_callout_paragraph(document, "复习抓手：")
        tip = add_body_paragraph(document, item["review_tip"])
        shade_paragraph(tip, TIP_SHADE)
    if item["knowledge_points"]:
        add_callout_paragraph(document, "知识补充：")
        for point in item["knowledge_points"]:
            add_list_paragraph(document, point)
    if item["principles"]:
        add_callout_paragraph(document, "同类题判断法：")
        for principle in item["principles"]:
            add_list_paragraph(document, principle)


def add_callout_paragraph(document, text: str) -> None:
    from docx.shared import Pt, RGBColor

    paragraph = document.add_paragraph()
    run = paragraph.add_run(text)
    run.bold = True
    run.font.size = Pt(CALLOUT_FONT_SIZE_PT)
    run.font.color.rgb = RGBColor(0, 0, 0)


def add_body_paragraph(document, text: str):
    from docx.shared import Pt

    paragraph = document.add_paragraph(text)
    paragraph.paragraph_format.left_indent = Pt(12)
    paragraph.paragraph_format.space_after = Pt(8)
    paragraph.paragraph_format.line_spacing = 1.18
    return paragraph


def add_list_paragraph(document, text: str):
    from docx.shared import Pt

    paragraph = document.add_paragraph(text, style="List Bullet")
    paragraph.paragraph_format.left_indent = Pt(18)
    paragraph.paragraph_format.space_after = Pt(6)
    paragraph.paragraph_format.line_spacing = 1.15
    return paragraph


def add_memory_answer_paragraph(document, text: str):
    from docx.shared import Pt, RGBColor

    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = Pt(8)
    paragraph.paragraph_format.space_before = Pt(3)
    paragraph.paragraph_format.space_after = Pt(8)
    paragraph.paragraph_format.line_spacing = 1.28
    run = paragraph.add_run(text)
    run.bold = True
    run.font.size = Pt(CALLOUT_FONT_SIZE_PT)
    run.font.color.rgb = RGBColor(31, 58, 95)
    shade_paragraph(paragraph, MEMORY_ANSWER_SHADE)
    add_left_border(paragraph, MEMORY_ACCENT_COLOR)
    return paragraph


def add_memory_fields_table(document, fields: list[tuple[str, str, bool, str | None]]):
    from docx.shared import Inches, Pt, RGBColor

    rows = [
        (label, format_math_text(value), bold_value, fill)
        for label, value, bold_value, fill in fields
        if format_math_text(value)
    ]
    if not rows:
        return None
    table = document.add_table(rows=len(rows), cols=2)
    table.autofit = False
    remove_table_borders(table)
    for row, (label, value, bold_value, fill) in zip(table.rows, rows, strict=True):
        label_cell, value_cell = row.cells
        label_cell.width = Inches(0.78)
        value_cell.width = Inches(5.55)
        set_cell_margins(label_cell, top=45, bottom=45, start=0, end=80)
        set_cell_margins(value_cell, top=45, bottom=45, start=20, end=0)
        if fill:
            shade_cell(label_cell, fill)
            shade_cell(value_cell, fill)

        label_paragraph = label_cell.paragraphs[0]
        label_paragraph.paragraph_format.space_after = Pt(5)
        label_paragraph.paragraph_format.line_spacing = 1.35
        label_run = label_paragraph.add_run(f"{label}：")
        label_run.bold = True
        label_run.font.size = Pt(10.5)
        label_run.font.color.rgb = RGBColor(176, 90, 107)

        value_paragraph = value_cell.paragraphs[0]
        value_paragraph.paragraph_format.space_after = Pt(5)
        value_paragraph.paragraph_format.line_spacing = 1.35
        value_run = value_paragraph.add_run(value)
        value_run.bold = bold_value
        value_run.font.size = Pt(10.5)
        value_run.font.color.rgb = RGBColor(33, 37, 41)
    spacer = document.add_paragraph()
    spacer.paragraph_format.space_after = Pt(4)
    return table


def add_memory_field_paragraph(
    document,
    label: str,
    value: str,
    *,
    bold_value: bool = False,
    fill: str | None = None,
):
    from docx.shared import Pt, RGBColor

    text = format_math_text(value)
    if not text:
        return None
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.left_indent = Pt(12)
    paragraph.paragraph_format.space_after = Pt(4.5)
    paragraph.paragraph_format.line_spacing = 1.24
    label_run = paragraph.add_run(f"{label}：")
    label_run.bold = True
    label_run.font.size = Pt(10.5)
    label_run.font.color.rgb = RGBColor(176, 90, 107)
    value_run = paragraph.add_run(text)
    value_run.bold = bold_value
    value_run.font.size = Pt(10.5)
    value_run.font.color.rgb = RGBColor(33, 37, 41)
    if fill:
        shade_paragraph(paragraph, fill)
        add_left_border(paragraph, "C8A24A")
    return paragraph


def shade_paragraph(paragraph, fill: str) -> None:
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    paragraph._p.get_or_add_pPr().append(
        parse_xml(f'<w:shd {nsdecls("w")} w:fill="{escape(fill)}"/>')
    )


def shade_cell(cell, fill: str) -> None:
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    cell._tc.get_or_add_tcPr().append(
        parse_xml(f'<w:shd {nsdecls("w")} w:fill="{escape(fill)}"/>')
    )


def remove_table_borders(table) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = borders.find(qn(f"w:{edge}"))
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        element.set(qn("w:val"), "nil")


def set_cell_margins(cell, *, top: int, bottom: int, start: int, end: int) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tc_pr = cell._tc.get_or_add_tcPr()
    margins = tc_pr.first_child_found_in("w:tcMar")
    if margins is None:
        margins = OxmlElement("w:tcMar")
        tc_pr.append(margins)
    for key, value in {
        "top": top,
        "bottom": bottom,
        "start": start,
        "end": end,
    }.items():
        node = margins.find(qn(f"w:{key}"))
        if node is None:
            node = OxmlElement(f"w:{key}")
            margins.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def add_left_border(paragraph, color: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "16")
    left.set(qn("w:space"), "6")
    left.set(qn("w:color"), color)
    borders.append(left)
    p_pr.append(borders)


def add_separator(document) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    paragraph = document.add_paragraph()
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "dashed")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "8")
    bottom.set(qn("w:color"), LINE_COLOR)
    borders.append(bottom)
    p_pr.append(borders)


def load_enriched_questions(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    questions = data if isinstance(data, list) else data.get("questions", [])
    return [dict(question) for question in questions]


def _memory_progress_path(input_path: Path, output_dir: Path) -> Path:
    if input_path.name.endswith(".enriched.json"):
        return input_path
    return output_dir / "questions.enriched.json"


def _write_memory_markdown(output_dir: Path, title: str, questions: list[dict]) -> Path:
    memory_title = title if title.endswith("速记刷背") else f"{title}-速记刷背"
    path = output_dir / f"{memory_title}.md"
    path.write_text(render_memory_markdown(questions, memory_title), encoding="utf-8")
    return path


def _write_memory_docx(output_dir: Path, title: str, questions: list[dict]) -> Path:
    memory_title = title if title.endswith("速记刷背") else f"{title}-速记刷背"
    path = output_dir / f"{memory_title}.docx"
    write_memory_docx(questions, memory_title, path)
    return path


def build_outputs(
    args: argparse.Namespace,
    *,
    memory_client: Callable[[list[dict]], str] = call_chat_completion,
) -> list[dict]:
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    title = args.title or input_path.name or "学习通作业复习资料"
    cache_path = Path(args.cache) if args.cache else output_dir / "explanations.cache.json"
    load_dotenv(Path.cwd() / ".env")
    if input_path.is_dir():
        load_dotenv(input_path / ".env")
    if args.verify_answers is None:
        args.verify_answers = env_flag("VERIFY_ANSWERS", False)

    memory_enabled = memory_enabled_from_args(args)
    memory_only = bool(getattr(args, "memory_only", False))
    model = os.getenv("AI_MODEL") or "deepseek-v4-flash"
    vision = "开启" if env_flag("AI_VISION_ENABLED") else "关闭"
    verify = "开启" if args.verify_answers else "关闭"
    memory_label = "开启" if memory_enabled or memory_only else "关闭"
    font = os.getenv("DOCX_FONT") or "Microsoft YaHei"
    print(
        f"[info] 模型：{model}  |  图片识别：{vision}  |  答案校验：{verify}  |  速记卡：{memory_label}  |  文档字体：{font}",
        flush=True,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    if memory_only:
        questions = load_enriched_questions(input_path) if input_path.name.endswith(".enriched.json") else load_questions(input_path)
        questions = apply_limit(questions, args.limit)
        cache = load_cache(cache_path)
        progress_path = _memory_progress_path(input_path, output_dir)

        def write_memory_progress(progress_cache: dict[str, dict], processed: list[dict]) -> None:
            save_json(cache_path, progress_cache)
            save_json(progress_path, processed)

        enriched = enrich_memory_cards(
            questions,
            client=memory_client,
            cache=cache,
            dry_run=args.dry_run,
            cache_writer=write_memory_progress,
        )
        cache = update_cache(cache, enriched)
        save_json(cache_path, cache)
        save_json(progress_path, enriched)
        memory_path = _write_memory_markdown(output_dir, title, enriched)
        memory_docx_path = _write_memory_docx(output_dir, title, enriched)
        print(f"- 速记刷背：{memory_path}", flush=True)
        print(f"- 速记刷背 DOCX：{memory_docx_path}", flush=True)
        return enriched

    questions = load_questions(input_path)
    questions = apply_limit(questions, args.limit)
    cache = load_cache(cache_path)
    cached_count = sum(1 for question in questions if question_key(question) in cache)
    print(f"输入题目：{len(questions)}", flush=True)
    print(f"已有缓存：{cached_count}", flush=True)
    print(f"开启答案校验：{'是' if args.verify_answers and not args.dry_run else '否'}", flush=True)

    def write_progress_cache(progress_cache: dict[str, dict], processed: list[dict]) -> None:
        save_json(cache_path, progress_cache)
        save_json(output_dir / "questions.partial.json", processed)

    def on_consecutive_failures(count, failed):
        answer = input(f"连续 {count} 题解析失败。已保存进度，是否继续？ [Y/n](y) ").strip().lower()
        return not answer or answer in {"y", "yes", "是"}

    enriched = enrich_questions(
        questions,
        cache=cache,
        dry_run=args.dry_run,
        verify_answers=args.verify_answers and not args.dry_run,
        cache_writer=write_progress_cache,
        on_consecutive_failures=on_consecutive_failures,
    )
    cache = update_cache(cache, enriched)
    if memory_enabled:
        enriched = enrich_memory_cards(
            enriched,
            client=memory_client,
            cache=cache,
            dry_run=args.dry_run,
            cache_writer=write_progress_cache,
        )
        cache = update_cache(cache, enriched)

    save_json(output_dir / "questions.enriched.json", enriched)
    save_json(cache_path, cache)
    (output_dir / "review-needed.md").write_text(
        render_review_needed_markdown(enriched, f"{title}-需复核题目"),
        encoding="utf-8",
    )
    (output_dir / f"{title}.md").write_text(
        render_markdown(enriched, title), encoding="utf-8"
    )
    docx_failed = False
    try:
        write_docx(enriched, title, output_dir / f"{title}.docx")
    except PermissionError:
        docx_failed = True
    memory_path = _write_memory_markdown(output_dir, title, enriched) if memory_enabled else None
    memory_docx_path = _write_memory_docx(output_dir, title, enriched) if memory_enabled else None
    print_run_summary(
        build_run_summary(enriched),
        output_dir,
        title,
        docx_failed=docx_failed,
        review_needed_path=output_dir / "review-needed.md",
    )
    if memory_path:
        print(f"- 速记刷背：{memory_path}", flush=True)
    if memory_docx_path:
        print(f"- 速记刷背 DOCX：{memory_docx_path}", flush=True)
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
    parser.add_argument(
        "--verify-answers",
        action="store_true",
        default=None,
        help="Ask the model to independently check exported answers and flag risks.",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="Generate memory-card Markdown in addition to the full review outputs.",
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Disable memory-card generation even if MEMORY_CARDS_ENABLED is true.",
    )
    parser.add_argument(
        "--memory-only",
        action="store_true",
        help="Only generate memory-card Markdown from existing JSON/enriched JSON.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Process only the first N questions. Useful for testing API output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        enriched = build_outputs(args)
        print(f"Processed {len(enriched)} questions.")
    except KeyboardInterrupt:
        print("\n用户中断。已处理的部分已保存至输出目录，重新运行命令可继续处理剩余题目。")
        return 1
    return 0


if __name__ == "__main__":
    main()
