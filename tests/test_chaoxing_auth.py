from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import chaoxing_auth


class FakePlaywrightError(Exception):
    pass


class FakePage:
    def __init__(self, events: list[str], *, close_on_second_goto: bool = False):
        self.events = events
        self.close_on_second_goto = close_on_second_goto
        self.goto_count = 0

    def goto(self, url: str) -> None:
        self.goto_count += 1
        self.events.append("goto")
        if self.close_on_second_goto and self.goto_count == 2:
            raise FakePlaywrightError("Target page, context or browser has been closed")

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.events.append("wait_for_load_state")


class FakeContext:
    def __init__(self, page: FakePage, events: list[str]):
        self.page = page
        self.events = events

    def new_page(self) -> FakePage:
        return self.page

    def storage_state(self, path: str) -> None:
        self.events.append("storage_state")
        Path(path).write_text('{"cookies": []}', encoding="utf-8")


class FakeBrowser:
    def __init__(self, context: FakeContext, events: list[str]):
        self.context = context
        self.events = events

    def new_context(self) -> FakeContext:
        return self.context

    def close(self) -> None:
        self.events.append("browser.close")


class FakeChromium:
    def __init__(self, browser: FakeBrowser):
        self.browser = browser

    def launch(self, **kwargs) -> FakeBrowser:
        return self.browser


class FakeSyncPlaywright:
    def __init__(self, browser: FakeBrowser):
        self.chromium = FakeChromium(browser)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def install_fake_playwright(browser: FakeBrowser) -> None:
    fake_sync_api = types.SimpleNamespace(
        Error=FakePlaywrightError,
        sync_playwright=lambda: FakeSyncPlaywright(browser),
    )
    sys.modules["playwright"] = types.SimpleNamespace(sync_api=fake_sync_api)
    sys.modules["playwright.sync_api"] = fake_sync_api


class ChaoxingAuthLoginTests(unittest.TestCase):
    def setUp(self):
        self.original_playwright_modules = {
            name: sys.modules.get(name) for name in ("playwright", "playwright.sync_api")
        }

    def tearDown(self):
        for name, module in self.original_playwright_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_closed_browser_after_enter_raises_friendly_retry_message(self):
        events: list[str] = []
        page = FakePage(events, close_on_second_goto=True)
        context = FakeContext(page, events)
        browser = FakeBrowser(context, events)
        install_fake_playwright(browser)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("builtins.input", return_value=""):
                with patch("scripts.chaoxing_auth.time.sleep"):
                    with self.assertRaisesRegex(RuntimeError, "浏览器窗口已关闭.*重新运行"):
                        chaoxing_auth.login_with_playwright(Path(tmp) / "state.json")

        self.assertIn("browser.close", events)

    def test_login_instructions_and_delay_happen_before_opening_browser_page(self):
        events: list[str] = []
        page = FakePage(events)
        context = FakeContext(page, events)
        browser = FakeBrowser(context, events)
        install_fake_playwright(browser)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("builtins.print", side_effect=lambda *args, **kwargs: events.append("print")):
                with patch("builtins.input", side_effect=lambda *args, **kwargs: events.append("input") or ""):
                    with patch("scripts.chaoxing_auth.time.sleep", side_effect=lambda seconds: events.append(f"sleep:{seconds}")):
                        with patch("scripts.chaoxing_auth.load_cookies_from_state", return_value=[{"name": "uid"}]):
                            with patch("scripts.chaoxing_auth.chaoxing_client.ChaoxingClient") as client_cls:
                                client_cls.return_value.ensure_logged_in.return_value = True

                                chaoxing_auth.login_with_playwright(Path(tmp) / "state.json")

        self.assertLess(events.index("print"), events.index("sleep:3"))
        self.assertLess(events.index("sleep:3"), events.index("goto"))


if __name__ == "__main__":
    unittest.main()
