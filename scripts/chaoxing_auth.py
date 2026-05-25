"""Playwright-assisted Chaoxing login state management."""

from __future__ import annotations

import os
from pathlib import Path

from scripts import chaoxing_client


DEFAULT_STATE_PATH = Path(".local/chaoxing_state.json")
LOGIN_URL = "https://mooc1-1.chaoxing.com/visit/interaction"


def state_path_from_env() -> Path:
    return Path(os.getenv("CHAOXING_STATE_PATH", str(DEFAULT_STATE_PATH)))


def headless_from_env() -> bool:
    return os.getenv("CHAOXING_HEADLESS", "false").strip().lower() in {"1", "true", "yes"}


def load_cookies_from_state(path: Path | None = None) -> list[dict]:
    path = path or state_path_from_env()
    if not path.exists():
        return []
    return chaoxing_client.cookies_from_storage_state(chaoxing_client.load_storage_state(path))


def ensure_login_state(path: Path | None = None, headless: bool | None = None) -> Path:
    path = path or state_path_from_env()
    cookies = load_cookies_from_state(path)
    if cookies:
        client = chaoxing_client.ChaoxingClient(cookies)
        try:
            if client.ensure_logged_in():
                return path
        except Exception:
            pass
    return login_with_playwright(path, headless=headless_from_env() if headless is None else headless)


def login_with_playwright(path: Path, *, headless: bool = False) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("缺少 playwright 依赖，请先运行 uv sync。") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright, headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL)
        print("请在打开的浏览器中完成学习通登录。登录后回到终端按 Enter。", flush=True)
        input()
        page.goto(LOGIN_URL)
        page.wait_for_load_state("domcontentloaded", timeout=30000)
        context.storage_state(path=str(path))
        browser.close()
    cookies = load_cookies_from_state(path)
    client = chaoxing_client.ChaoxingClient(cookies)
    if not client.ensure_logged_in():
        raise RuntimeError("未检测到有效学习通登录态，请重新运行并完成登录。")
    return path


def _launch_browser(playwright, *, headless: bool):
    errors: list[str] = []
    for kwargs in (
        {"channel": "msedge", "headless": headless},
        {"channel": "chrome", "headless": headless},
        {"headless": headless},
    ):
        try:
            return playwright.chromium.launch(**kwargs)
        except Exception as exc:  # pragma: no cover - depends on local browser install.
            errors.append(str(exc).splitlines()[0])
    raise RuntimeError(
        "无法启动 Playwright 浏览器。请运行 `uv run playwright install chromium` 后重试。"
        f" 启动错误：{'; '.join(errors)}"
    )
