"""Interactive entry point for Chaoxing homework collection and review."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from scripts import chaoxing_auth, chaoxing_client, chaoxing_collect, homework_review


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Chaoxing homework and generate review docs.")
    parser.add_argument("--output-dir", default=None, help="Output directory. Defaults to CHAOXING_OUTPUT_DIR or output.")
    parser.add_argument("--no-review", action="store_true", help="Collect JSON only, without running homework-review.")
    parser.add_argument("--verify-answers", action="store_true", help="Enable answer verification during review.")
    parser.add_argument("--course", action="append", help="Course keyword. Can be repeated. Skips the course search prompt.")
    parser.add_argument("--yes", action="store_true", help="Use defaults for prompts when possible.")
    args = parser.parse_args()

    homework_review.load_dotenv()
    output_root = Path(args.output_dir or os.getenv("CHAOXING_OUTPUT_DIR", "output"))

    state_path = chaoxing_auth.ensure_login_state()
    client = chaoxing_client.ChaoxingClient(chaoxing_auth.load_cookies_from_state(state_path))
    courses = client.get_courses()
    print(f"已读取课程：{len(courses)} 门", flush=True)
    selected_courses = choose_courses(courses, args.course, assume_yes=args.yes)
    if not selected_courses:
        print("未选择课程，已退出。", flush=True)
        return

    collected_by_course: dict[str, list[Path]] = {}
    for course in selected_courses:
        course_name = course["name"]
        print(f"\n读取课程：{course_name}", flush=True)
        try:
            course_page = client.get_course_page(course)
            works = client.get_works(course_page)
        except Exception as exc:
            print(f"跳过课程：{course_name}。原因：{exc}", flush=True)
            continue
        completed = [work for work in works if work.get("status") == "已完成"]
        selected_works = choose_works(course_name, completed, assume_yes=args.yes)
        if not selected_works:
            print(f"未选择作业：{course_name}", flush=True)
            continue
        raw_dir = output_root / chaoxing_collect.safe_filename(course_name) / "raw"
        written: list[Path] = []
        for index, work in enumerate(selected_works, 1):
            print(f"[{index}/{len(selected_works)}] 采集：{work['title']}", flush=True)
            try:
                homework = client.get_homework(course_name, work, referer=course_page.get("work_list_url"))
                path = chaoxing_collect.write_homework_json(raw_dir, homework)
                written.append(path)
            except Exception as exc:
                print(f"采集失败：{work.get('title', work.get('url'))}。原因：{exc}", flush=True)
        if written:
            collected_by_course[course_name] = written
            print(f"已导出 {len(written)} 个 JSON 到：{raw_dir}", flush=True)

    if not collected_by_course:
        print("没有成功采集到作业。", flush=True)
        return
    if args.no_review:
        return
    review_default = os.getenv("CHAOXING_REVIEW_AFTER_COLLECT", "true").lower() in {"1", "true", "yes"}
    if not args.yes and not confirm("是否立即生成复习资料？", default=review_default):
        return
    for course_name in collected_by_course:
        run_review_for_course(output_root, course_name, verify_answers=args.verify_answers)


def choose_courses(courses: list[dict], keywords: list[str] | None, *, assume_yes: bool = False) -> list[dict]:
    if keywords:
        selected = [
            course
            for course in courses
            if any(keyword.lower() in course["name"].lower() for keyword in keywords)
        ]
        return selected
    if assume_yes:
        return courses[:1]
    keyword = input("请输入课程关键词，留空显示前 20 门课程：").strip()
    filtered = [
        course for course in courses if not keyword or keyword.lower() in course["name"].lower()
    ]
    filtered = sort_courses_by_start_date(filtered)
    filtered = filtered[:50]
    if not filtered:
        print(f"未找到匹配课程。当前已读取 {len(courses)} 门课程。", flush=True)
        return []
    return multi_select(
        "选择课程",
        filtered,
        course_label,
    )


def choose_works(course_name: str, works: list[dict], *, assume_yes: bool = False) -> list[dict]:
    if assume_yes:
        return works
    if not works:
        return []
    return multi_select(
        f"选择作业：{course_name}",
        works,
        lambda work: f"{work['title']}  {work.get('status', '')}",
        default_all=True,
    )


def sort_courses_by_start_date(courses: list[dict]) -> list[dict]:
    return sorted(courses, key=lambda course: course.get("start_date") or "", reverse=True)


def course_label(course: dict) -> str:
    date = course.get("start_date", "")
    suffix = f" 开课:{date}" if date else ""
    return f"{course['name']} ({course.get('course_id')}/{course.get('class_id')}){suffix}"


def multi_select(message: str, choices: list[dict], labeler, *, default_all: bool = False) -> list[dict]:
    if not choices:
        return []
    try:
        from InquirerPy import inquirer

        selected = inquirer.checkbox(
            message=message,
            choices=[{"name": labeler(item), "value": item, "enabled": default_all} for item in choices],
            instruction="空格选择，回车确认",
        ).execute()
        if selected or default_all:
            return list(selected)
        print("未勾选项目，改用编号选择。", flush=True)
    except Exception:
        pass
    return numbered_select(choices, labeler)


def numbered_select(choices: list[dict], labeler) -> list[dict]:
    for index, item in enumerate(choices, 1):
        print(f"{index}. {labeler(item)}", flush=True)
    raw = input("输入编号，多个用逗号分隔；留空表示全选：").strip()
    if not raw:
        return choices
    indexes = {int(part) for part in raw.split(",") if part.strip().isdigit()}
    return [item for index, item in enumerate(choices, 1) if index in indexes]


def confirm(message: str, *, default: bool = True) -> bool:
    suffix = "[Y/n](y)" if default else "[y/N](n)"
    answer = input(f"{message} {suffix} ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "是"}


def run_review_for_course(output_root: Path, course_name: str, *, verify_answers: bool) -> None:
    safe_course = chaoxing_collect.safe_filename(course_name)
    raw_dir = output_root / safe_course / "raw"
    review_dir = output_root / safe_course / "review"
    title = f"{course_name}-完整复习资料"
    print(f"生成复习资料：{course_name}", flush=True)
    questions = homework_review.load_questions(raw_dir)
    cache_path = review_dir / "explanations.cache.json"
    review_dir.mkdir(parents=True, exist_ok=True)
    cache = homework_review.load_cache(cache_path)

    def cache_writer(updated_cache, processed):
        homework_review.save_json(cache_path, updated_cache)
        homework_review.save_json(review_dir / "questions.partial.json", processed)

    enriched = homework_review.enrich_questions(
        questions,
        cache=cache,
        verify_answers=verify_answers,
        cache_writer=cache_writer,
    )
    cache = homework_review.update_cache(cache, enriched)
    homework_review.save_json(cache_path, cache)
    homework_review.save_json(review_dir / "questions.enriched.json", enriched)
    (review_dir / "review-needed.md").write_text(
        homework_review.render_review_needed_markdown(enriched, f"{title}-需复核题目"),
        encoding="utf-8",
    )
    (review_dir / f"{title}.md").write_text(
        homework_review.render_markdown(enriched, title), encoding="utf-8"
    )
    homework_review.write_docx(enriched, title, review_dir / f"{title}.docx")
    homework_review.print_run_summary(
        homework_review.build_run_summary(enriched), review_dir, title
    )


if __name__ == "__main__":
    main()
