"""Local, user-visible Yuanbao reauthorization for WeChat Channels downloads."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from tempfile import TemporaryDirectory

from .local_credentials import save_yuanbao_cookie

YUANBAO_HOME_URL = 'https://yuanbao.tencent.com/'


def build_cookie_header(cookies: Iterable[dict]) -> str:
    """Turn Playwright cookie records into an HTTP Cookie header without logging it."""
    pairs: list[str] = []
    for cookie in cookies:
        name = str(cookie.get('name', '')).strip()
        value = str(cookie.get('value', '')).strip()
        if name and value:
            pairs.append(f'{name}={value}')
    return '; '.join(pairs)


class YuanbaoAuthorizationSession:
    """Run a visible, temporary browser and save only after the owner confirms login."""

    def __init__(
        self,
        on_opened: Callable[[], None],
        on_success: Callable[[], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._on_opened = on_opened
        self._on_success = on_success
        self._on_error = on_error
        self._finish_requested = threading.Event()
        self._cancelled = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name='yuanbao-authorization').start()

    def finish_login(self) -> None:
        self._finish_requested.set()

    def cancel(self) -> None:
        self._cancelled.set()

    def _run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._on_error('缺少授权浏览器组件。请重新运行 setup.bat 后重试。')
            return

        try:
            with TemporaryDirectory(prefix='video-download-yuanbao-') as profile_dir:
                with sync_playwright() as playwright:
                    try:
                        context = playwright.chromium.launch_persistent_context(
                            profile_dir, channel='chrome', headless=False
                        )
                    except Exception:
                        context = playwright.chromium.launch_persistent_context(
                            profile_dir, headless=False
                        )
                    try:
                        page = context.pages[0] if context.pages else context.new_page()
                        page.goto(YUANBAO_HOME_URL, wait_until='domcontentloaded', timeout=60_000)
                        self._on_opened()
                        while not self._finish_requested.wait(0.2):
                            if self._cancelled.is_set():
                                return
                        if self._cancelled.is_set():
                            return
                        header = build_cookie_header(context.cookies([YUANBAO_HOME_URL]))
                        if not header:
                            self._on_error('未检测到登录信息。请确认已在打开的元宝窗口完成登录。')
                            return
                        save_yuanbao_cookie(header)
                        self._on_success()
                    finally:
                        context.close()
        except Exception:
            self._on_error('无法完成一键授权。请检查网络，或改用手动输入。')