"""Parse Chaoxing course, homework list, and homework detail pages."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup


CHAOXING_HOST = "https://mooc1.chaoxing.com"


def clean_text(value: object) -> str:
    text = unescape(str(value or ""))
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def parse_course_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    courses: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for anchor in soup.select('a[href*="stucoursemiddle"]'):
        container = anchor.find_parent(attrs={"courseid": True}) or anchor
        name = _course_name(anchor, container)
        if not name:
            continue
        href = anchor.get("href", "")
        params = _query_params(href)
        course = {
            "name": name,
            "url": href,
            "course_id": params.get("courseid") or params.get("courseId") or container.get("courseid", ""),
            "class_id": params.get("clazzid") or params.get("classId") or container.get("clazzid", ""),
            "cpi": params.get("cpi") or container.get("personid", ""),
        }
        course.update(_course_dates(container))
        key = (course["name"], course["course_id"], course["class_id"])
        if key in seen:
            continue
        seen.add(key)
        courses.append(course)
    return courses


def parse_course_page(html: str, page_url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    params = {
        "course_id": _input_value(soup, "courseid") or _input_value(soup, "courseId"),
        "class_id": _input_value(soup, "clazzid") or _input_value(soup, "classId"),
        "cpi": _input_value(soup, "cpi"),
        "student_enc": _input_value(soup, "enc"),
        "work_enc": _input_value(soup, "workEnc"),
        "t": _input_value(soup, "t"),
    }
    work_nav = _find_work_nav(soup)
    work_list_url = ""
    if work_nav and work_nav.get("data_url"):
        work_list_url = build_work_list_url(work_nav["data_url"], params, page_url)
    return {
        "title": clean_text(soup.title.string if soup.title else ""),
        "url": page_url,
        "params": params,
        "work_nav": work_nav,
        "work_list_url": work_list_url,
    }


def build_work_list_url(data_url: str, params: dict, page_url: str = "") -> str:
    base = urljoin(page_url or CHAOXING_HOST, data_url)
    query = {
        "courseId": params.get("course_id", ""),
        "classId": params.get("class_id", ""),
        "cpi": params.get("cpi", ""),
        "ut": "s",
        "t": params.get("t", ""),
        "stuenc": params.get("student_enc", ""),
        "enc": params.get("work_enc", ""),
    }
    query = {key: value for key, value in query.items() if value}
    return base + "?" + urlencode(query)


def parse_work_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    works: list[dict] = []
    for item in soup.select('li[data][onclick*="goTask"]'):
        text = clean_text(item.get_text(" "))
        title = clean_text(item.select_one("p").get_text(" ") if item.select_one("p") else text)
        title = _clean_work_title(title)
        detail_url = item.get("data", "")
        params = _query_params(detail_url)
        works.append(
            {
                "title": title,
                "status": _work_status(text),
                "text": text,
                "url": detail_url,
                "work_id": params.get("workId") or params.get("workid"),
                "answer_id": params.get("answerId") or params.get("answerid"),
                "enc": params.get("enc"),
            }
        )
    return works


def parse_work_detail(
    html: str,
    *,
    course_name: str,
    homework_title: str,
    detail_url: str,
) -> dict:
    soup = BeautifulSoup(html, "lxml")
    params = _query_params(detail_url)
    questions = [
        _parse_question_block(block, index)
        for index, block in enumerate(soup.select(".singleQuesId"), 1)
    ]
    return {
        "source": "chaoxing",
        "meta": {
            "courseName": course_name,
            "homeworkTitle": homework_title or _infer_homework_title(soup),
            "courseId": params.get("courseId") or params.get("courseid"),
            "classId": params.get("classId") or params.get("classid"),
            "workId": params.get("workId") or params.get("workid"),
            "answerId": params.get("answerId") or params.get("answerid"),
            "detailUrl": detail_url,
        },
        "questions": [question for question in questions if question.get("question")],
    }


def _parse_question_block(block, index: int) -> dict:
    question_id = block.get("id") or block.get("data") or ""
    q_type = _question_type(block)
    options = _options(block)
    option_lines = [f"{item['label']}. {item['text']}".strip() for item in options]
    student_answer = _answer_text(block, ".stuAnswerContent")
    correct_answer = _answer_text(block, ".rightAnswerContent")
    if not student_answer:
        student_answer = _answer_from_label(block, "我的答案")
    if not correct_answer:
        correct_answer = _answer_from_label(block, "正确答案")
    answer_visibility = _answer_visibility(student_answer, correct_answer)
    answer = correct_answer or student_answer
    return {
        "index": index,
        "id": question_id,
        "type": q_type,
        "question": _question_text(block, q_type),
        "options": option_lines,
        "option_items": options,
        "student_answer": student_answer,
        "correct_answer": correct_answer,
        "answer": answer,
        "score": _score(block),
        "analysis": "",
        "answer_visibility": answer_visibility,
        "raw_preview": clean_text(block.get_text(" "))[:500],
    }


def _question_type(block) -> str:
    text = clean_text(_first_text(block, ".colorShallow"))
    if not text:
        match = re.search(r"[（(](单选题|多选题|判断题|填空题)[）)]", block.get_text(" "))
        text = match.group(1) if match else ""
    return text.strip("()（） ")


def _question_text(block, q_type: str) -> str:
    lines = [clean_text(line) for line in block.get_text("\n").splitlines()]
    lines = [line for line in lines if line]
    option_start = next((i for i, line in enumerate(lines) if _looks_like_option(line)), len(lines))
    before_options = lines[:option_start]
    filtered = []
    for line in before_options:
        if any(marker in line for marker in ["我的答案", "正确答案", "AI讲解"]):
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?分", line):
            continue
        filtered.append(line)
    text = clean_text(" ".join(filtered))
    text = re.sub(r"^\d+[.．、]\s*", "", text)
    text = re.sub(rf"[（(]{re.escape(q_type)}[）)]\s*", "", text)
    text = _strip_inline_question_tail(text)
    return clean_text(text)


def _options(block) -> list[dict]:
    option_items = []
    nodes = block.select("ul li")
    if nodes:
        raw_options = [clean_text(node.get_text(" ")) for node in nodes]
    else:
        raw_options = [
            clean_text(line)
            for line in block.get_text("\n").splitlines()
            if _looks_like_option(clean_text(line))
        ]
    for raw in raw_options:
        match = re.match(r"^([A-Z])\s*[.．、]\s*(.*)$", raw)
        if match:
            option_items.append({"label": match.group(1), "text": clean_text(match.group(2))})
        elif raw:
            option_items.append({"label": "", "text": raw})
    return option_items


def _score(block) -> str:
    score = _first_text(block, ".mark_score")
    if score:
        return clean_text(score)
    match = re.search(r"\d+(?:\.\d+)?分", block.get_text(" "))
    return match.group(0) if match else ""


def _strip_inline_question_tail(text: str) -> str:
    text = re.split(r"\s+[A-Z]\s*[.．、]\s*\S+", text, maxsplit=1)[0]
    text = re.sub(r"\s+[A-Z]\s*[:：].*$", "", text)
    text = re.sub(r"\s+[A-Z]\s*[.．、]\s*$", "", text)
    text = re.sub(r"\s+\d+(?:\.\d+)?\s*分$", "", text)
    return text


def _answer_visibility(student_answer: str, correct_answer: str) -> str:
    if correct_answer:
        return "correct_answer_visible"
    if student_answer:
        return "student_answer_only"
    return "answer_hidden"


def _answer_text(block, selector: str) -> str:
    values = [clean_text(node.get_text(" ")) for node in block.select(selector)]
    return "；".join(value for value in values if value)


def _answer_from_label(block, label: str) -> str:
    text = clean_text(block.get_text(" "))
    match = re.search(rf"{label}\s*[:：]\s*(.*?)(?:正确答案|AI讲解|\d+(?:\.\d+)?分|$)", text)
    if not match:
        return ""
    value = match.group(1)
    value = re.sub(r"\s*[:：][^;；]+[;；]?", "", value)
    return clean_text(value)


def _input_value(soup: BeautifulSoup, element_id: str) -> str:
    element = soup.find(id=element_id)
    return clean_text(element.get("value", "")) if element else ""


def _course_name(anchor, container) -> str:
    name_node = anchor.select_one(".course-name") or container.select_one(".course-name")
    if name_node:
        title = clean_text(name_node.get("title", ""))
        if title:
            return title
        text = clean_text(name_node.get_text(" "))
        if text:
            return text
    return clean_text(anchor.get_text(" "))


def _course_dates(container) -> dict[str, str]:
    text = clean_text(container.get_text(" "))
    match = re.search(r"开课时间[:：]\s*(\d{4}-\d{2}-\d{2})\s*[~～-]\s*(\d{4}-\d{2}-\d{2})", text)
    if not match:
        return {"start_date": "", "end_date": ""}
    return {"start_date": match.group(1), "end_date": match.group(2)}


def _find_work_nav(soup: BeautifulSoup) -> dict | None:
    for item in soup.select(".nav-content li, li"):
        text = clean_text(item.get_text(" "))
        dataname = item.get("dataname", "")
        anchor = item.find("a")
        data_url = anchor.get("data-url", "") if anchor else ""
        if text == "作业" or dataname == "zy":
            return {"text": text, "dataname": dataname, "data_url": data_url}
    return None


def _query_params(url: str) -> dict[str, str]:
    parsed = parse_qs(urlparse(url).query)
    return {key: values[0] for key, values in parsed.items() if values}


def _work_status(text: str) -> str:
    if "已完成" in text:
        return "已完成"
    if "未完成" in text:
        return "未完成"
    return ""


def _clean_work_title(title: str) -> str:
    title = re.sub(r"(已完成|未完成|作答记录|智能分析|剩余.*)$", "", title)
    return clean_text(title)


def _infer_homework_title(soup: BeautifulSoup) -> str:
    text = clean_text(soup.get_text(" "))
    match = re.search(r"作业详情\s+(.+?)\s+题量", text)
    return clean_text(match.group(1)) if match else ""


def _first_text(block, selector: str) -> str:
    element = block.select_one(selector)
    return clean_text(element.get_text(" ")) if element else ""


def _looks_like_option(text: str) -> bool:
    return bool(re.match(r"^[A-Z]\s*[.．、]\s*\S+", text))
