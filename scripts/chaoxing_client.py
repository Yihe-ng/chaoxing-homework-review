"""HTTP client for read-only Chaoxing homework collection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from scripts import chaoxing_parser


COURSE_LIST_URL = "https://mooc1-1.chaoxing.com/visit/interaction"
COURSE_LIST_DATA_URL = "https://mooc1-1.chaoxing.com/mooc-ans/visit/courselistdata"
COURSE_MIDDLE_URL = "https://mooc1-1.chaoxing.com/mooc-ans/visit/stucoursemiddle"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


class ChaoxingClientError(RuntimeError):
    pass


@dataclass
class PageResponse:
    url: str
    text: str


class ChaoxingClient:
    def __init__(self, cookies: list[dict] | None = None, timeout: int = 30):
        self.session = requests.Session()
        self.timeout = timeout
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        if cookies:
            self.load_cookies(cookies)

    def load_cookies(self, cookies: list[dict]) -> None:
        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if not name or value is None:
                continue
            self.session.cookies.set(
                name,
                value,
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )

    def fetch_text(self, url: str, referer: str | None = None) -> PageResponse:
        headers = {"Referer": referer} if referer else None
        response = self.session.get(url, headers=headers, timeout=self.timeout, allow_redirects=True)
        response.encoding = response.apparent_encoding or response.encoding
        if response.status_code >= 400:
            raise ChaoxingClientError(f"HTTP {response.status_code}: {url}")
        return PageResponse(url=response.url, text=response.text)

    def post_text(self, url: str, data: dict, referer: str | None = None) -> PageResponse:
        headers = {"Referer": referer} if referer else None
        response = self.session.post(url, data=data, headers=headers, timeout=self.timeout, allow_redirects=True)
        response.encoding = response.apparent_encoding or response.encoding
        if response.status_code >= 400:
            raise ChaoxingClientError(f"HTTP {response.status_code}: {url}")
        return PageResponse(url=response.url, text=response.text)

    def ensure_logged_in(self) -> bool:
        page = self.fetch_text(COURSE_LIST_URL)
        return is_logged_in_course_page(page.text)

    def get_courses(self) -> list[dict]:
        page = self.fetch_text(COURSE_LIST_URL)
        if not is_logged_in_course_page(page.text):
            raise ChaoxingClientError("学习通登录态无效，请重新登录。")
        courses = chaoxing_parser.parse_course_list(page.text)
        if courses:
            return courses
        data_page = self.post_text(
            COURSE_LIST_DATA_URL,
            data=course_list_data_payload(page.text),
            referer=COURSE_LIST_URL,
        )
        courses = chaoxing_parser.parse_course_list(data_page.text)
        if not courses:
            raise ChaoxingClientError("未读取到课程列表。学习通可能改版，或登录态没有课程访问权限。")
        return courses

    def get_course_page(self, course: dict) -> dict:
        url = course.get("url") or build_course_middle_url(course)
        page = self.fetch_text(url, referer=COURSE_LIST_URL)
        if is_permission_or_login_page(page.text):
            raise ChaoxingClientError(f"无法进入课程：{course.get('name', url)}")
        return chaoxing_parser.parse_course_page(page.text, page.url)

    def get_works(self, course_page: dict) -> list[dict]:
        url = course_page.get("work_list_url")
        if not url:
            raise ChaoxingClientError("课程没有可解析的作业入口。")
        page = self.fetch_text(url, referer=course_page.get("url"))
        if is_permission_or_login_page(page.text):
            raise ChaoxingClientError("无法进入作业列表，登录态可能失效。")
        return chaoxing_parser.parse_work_list(page.text)

    def get_homework(self, course_name: str, work: dict, referer: str | None = None) -> dict:
        page = self.fetch_text(work["url"], referer=referer)
        if is_permission_or_login_page(page.text):
            raise ChaoxingClientError(f"无法进入作业详情：{work.get('title', work['url'])}")
        return chaoxing_parser.parse_work_detail(
            page.text,
            course_name=course_name,
            homework_title=work.get("title", ""),
            detail_url=page.url,
        )


def build_course_middle_url(course: dict) -> str:
    query = {
        "courseid": course.get("course_id", ""),
        "clazzid": course.get("class_id", ""),
        "vc": "1",
        "cpi": course.get("cpi", ""),
        "ismooc2": "1",
        "v": "2",
    }
    return COURSE_MIDDLE_URL + "?" + urlencode({key: value for key, value in query.items() if value})


def is_logged_in_course_page(html: str) -> bool:
    if is_permission_or_login_page(html):
        return False
    return "stucoursemiddle" in html or "我学的课" in html


def is_permission_or_login_page(html: str) -> bool:
    markers = [
        "<title>登录",
        "用户登录",
        "账号登录",
        "passport2.chaoxing.com/login",
        "/passport/login",
        "没有此页面访问权限",
        "长时间没有操作",
        "温馨提示",
        "重新进入课程",
    ]
    text = html or ""
    return any(marker in text for marker in markers)


def course_list_data_payload(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html or "", "lxml")
    current_tab = soup.select_one(".course-tab .tab-item.current[coursetype]")
    return {
        "courseType": (
            chaoxing_parser.clean_text(current_tab.get("coursetype", ""))
            if current_tab
            else _element_value(soup, "courseType", "1")
        ),
        "courseFolderId": _element_value(soup, "courseFolderId", "0"),
        "baseEducation": _element_value(soup, "baseEducation", "0"),
        "superstarClass": _element_value(soup, "superstarClass", "0"),
        "courseFolderSize": _element_value(soup, "courseFolderSize", "0"),
    }


def _element_value(soup: BeautifulSoup, element_id: str, default: str) -> str:
    element = soup.find(id=element_id)
    value = chaoxing_parser.clean_text(element.get("value", "")) if element else ""
    return value or default


def cookies_from_storage_state(state: dict) -> list[dict]:
    return list(state.get("cookies", [])) if isinstance(state, dict) else []


def load_storage_state(path: Path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))
