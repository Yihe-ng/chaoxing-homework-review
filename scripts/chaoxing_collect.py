"""Collect Chaoxing homework exports and write review-compatible JSON."""

from __future__ import annotations

import json
import re
from pathlib import Path


def safe_filename(name: str, fallback: str = "homework") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned or fallback


def write_homework_json(output_root: Path, homework: dict) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    meta = homework.get("meta", {})
    stem = safe_filename(meta.get("homeworkTitle") or meta.get("workId") or "homework")
    path = output_root / f"{stem}.json"
    if path.exists():
        suffix = meta.get("workId") or _short_hash(json.dumps(homework, ensure_ascii=False))
        path = output_root / f"{stem}-{suffix}.json"
    path.write_text(json.dumps(homework, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def needs_answer_source_review(question: dict) -> bool:
    visibility = question.get("answer_visibility", "correct_answer_visible")
    return visibility != "correct_answer_visible"


def _short_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
