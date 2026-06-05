"""Build readable, non-overwriting review document names."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from scripts.chaoxing_collect import safe_filename


DEFAULT_MAX_TITLE_LENGTH = 120
CHINESE_DIGITS = {
    0: "零",
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
}
CN_TO_INT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def load_homework_titles(paths: list[Path]) -> list[str]:
    titles: list[str] = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        meta = data.get("meta", {}) if isinstance(data, dict) else {}
        title = str(meta.get("homeworkTitle", "")).strip()
        titles.append(title)
    return titles


def build_review_title(
    course_name: str,
    homework_titles: list[str],
    *,
    review_all: bool = False,
    max_length: int = DEFAULT_MAX_TITLE_LENGTH,
) -> str:
    if review_all:
        return safe_filename(f"{course_name}-完整复习资料")
    summary = build_review_scope_summary(course_name, homework_titles)
    title = safe_filename(f"{course_name}-{summary}-复习资料")
    if len(title) <= max_length:
        return title
    return _short_hashed_title(course_name, homework_titles, summary, max_length)


def build_review_scope_summary(
    course_name: str,
    homework_titles: list[str],
) -> str:
    cleaned = [clean_homework_title(course_name, title) for title in homework_titles]
    non_empty = [title for title in cleaned if title]
    if not non_empty:
        return f"本轮{len(homework_titles)}个作业"

    chapters = [_chapter_number(title) for title in non_empty]
    if all(number is not None for number in chapters):
        return _chapter_summary([int(number) for number in chapters])

    rounds = [_round_number(title) for title in non_empty]
    if all(number is not None for number in rounds):
        return "_".join(_ordinal(int(number)) for number in rounds) + "作业"

    display_titles = [_display_title(title) for title in non_empty]
    if len(display_titles) <= 4:
        summary = "_".join(display_titles)
    else:
        summary = "_".join(display_titles[:3]) + f"等{len(display_titles)}个作业"
    if any(_round_number(title) is not None for title in non_empty) and not summary.endswith("作业"):
        summary += "作业"
    return summary


def clean_homework_title(course_name: str, title: str) -> str:
    cleaned = str(title or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(rf"^《\s*{re.escape(course_name)}\s*》", "", cleaned)
    cleaned = re.sub(rf"^{re.escape(course_name)}", "", cleaned)
    cleaned = re.sub(r"^[\s\-—_：:]+", "", cleaned)
    return safe_filename(cleaned)


def unique_output_stem(review_dir: Path, preferred_stem: str, suffixes: list[str]) -> str:
    stem = safe_filename(preferred_stem)
    if not _stem_exists(review_dir, stem, suffixes):
        return stem
    index = 2
    while True:
        candidate = f"{stem}-{index}"
        if not _stem_exists(review_dir, candidate, suffixes):
            return candidate
        index += 1


def _stem_exists(review_dir: Path, stem: str, suffixes: list[str]) -> bool:
    return any((review_dir / f"{stem}{suffix}").exists() for suffix in suffixes)


def _chapter_number(title: str) -> int | None:
    match = re.search(r"第([一二三四五六七八九十两\d]+)章", title)
    if not match:
        return None
    return _number_token_to_int(match.group(1))


def _round_number(title: str) -> int | None:
    match = re.search(r"第([一二三四五六七八九十两\d]+)次作业", title)
    if not match:
        return None
    return _number_token_to_int(match.group(1))


def _number_token_to_int(token: str) -> int:
    if token.isdigit():
        return int(token)
    if token == "十":
        return 10
    if token.startswith("十"):
        return 10 + CN_TO_INT.get(token[1:], 0)
    if token.endswith("十"):
        return CN_TO_INT.get(token[:-1], 0) * 10
    if "十" in token:
        high, low = token.split("十", 1)
        return CN_TO_INT.get(high, 1) * 10 + CN_TO_INT.get(low, 0)
    return CN_TO_INT.get(token, 0)


def _number_to_chinese(number: int) -> str:
    if number <= 10:
        return CHINESE_DIGITS.get(number, str(number))
    if number < 20:
        return "十" + CHINESE_DIGITS.get(number - 10, "")
    if number < 100:
        tens, ones = divmod(number, 10)
        return CHINESE_DIGITS.get(tens, str(tens)) + "十" + (CHINESE_DIGITS.get(ones, "") if ones else "")
    return str(number)


def _ordinal(number: int) -> str:
    return f"第{_number_to_chinese(number)}次"


def _chapter_label(number: int) -> str:
    return f"第{_number_to_chinese(number)}章"


def _chapter_summary(numbers: list[int]) -> str:
    unique = sorted(set(numbers))
    if len(unique) >= 2 and unique == list(range(unique[0], unique[-1] + 1)):
        return f"第{_number_to_chinese(unique[0])}至{_number_to_chinese(unique[-1])}章"
    if len(unique) <= 5:
        return "_".join(_chapter_label(number) for number in unique)
    return "_".join(_chapter_label(number) for number in unique[:3]) + f"等{len(unique)}章"


def _display_title(title: str) -> str:
    round_number = _round_number(title)
    if round_number is not None:
        return _ordinal(round_number)
    return title


def _compact_summary(display_titles: list[str]) -> str:
    shortened = [_shorten_text(title, 12) for title in display_titles]
    if len(shortened) <= 4:
        return "_".join(shortened)
    return "_".join(shortened[:3]) + f"等{len(shortened)}个作业"


def _short_hashed_title(course_name: str, homework_titles: list[str], summary: str, max_length: int) -> str:
    digest = hashlib.sha1(json.dumps(homework_titles, ensure_ascii=False).encode("utf-8")).hexdigest()[:6]
    cleaned_titles = [clean_homework_title(course_name, title) for title in homework_titles]
    display_titles = [
        _display_title(title)
        for title in cleaned_titles
        if title
    ]
    compact = _compact_summary(display_titles)
    if not compact:
        compact = summary
    base = safe_filename(f"{course_name}-{compact}-{digest}-复习资料")
    if len(base) <= max_length:
        return base
    compact = _bounded_compact_summary(display_titles, max(8, max_length - len(safe_filename(f"{course_name}--{digest}-复习资料"))))
    base = safe_filename(f"{course_name}-{compact}-{digest}-复习资料")
    if len(base) <= max_length:
        return base
    budget = max(8, max_length - len(safe_filename(f"{course_name}--{digest}-复习资料")))
    compact = _shorten_text(compact, budget)
    return safe_filename(f"{course_name}-{compact}-{digest}-复习资料")


def _shorten_text(text: str, max_length: int) -> str:
    value = str(text or "").strip()
    if len(value) <= max_length:
        return value
    return value[:max_length].rstrip()


def _bounded_compact_summary(display_titles: list[str], max_length: int) -> str:
    if not display_titles:
        return "本轮作业"
    if len(display_titles) <= 4:
        joined = "_".join(display_titles)
        return _shorten_text(joined, max_length)
    tail = f"等{len(display_titles)}个作业"
    parts = [_shorten_text(title, 8) for title in display_titles[:3]]
    while parts and len("_".join(parts) + tail) > max_length:
        longest = max(range(len(parts)), key=lambda index: len(parts[index]))
        parts[longest] = _shorten_text(parts[longest], max(3, len(parts[longest]) - 1))
    return "_".join(parts) + tail
