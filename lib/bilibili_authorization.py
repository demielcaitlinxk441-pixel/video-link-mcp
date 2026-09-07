"""Local, user-visible Bilibili authorization for downloads."""

from __future__ import annotations

import threading
from collections.abc import Callable
from tempfile import TemporaryDirectory

from .local_credentials import save_bilibili_cookie
from .yuanbao_authorization import build_cookie_header

BILIBILI_HOME_URL = 'https://www.bilibili.com/'


def has_bilibili_login_cookie(cookie_header: str) -> bool:
    """Require the session cookie, not merely anonymous site preferences."""
    return any(
        part.strip().startswith('SESSDATA=')
        for part in (cookie_header or '').split(';')
    )


class BilibiliAuthorizationSession:
    """Run a visible temporary browser and save authorization after confirmation."""

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
        threading.Thread(target=self._run, daemon=True, name='bilibili-authorization').start()

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
            with TemporaryDirectory(prefix='video-download-bilibili-') as profile_dir:
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
                        page.goto(BILIBILI_HOME_URL, wait_until='domcontentloaded', timeout=60_000)
                        self._on_opened()
                        while not self._finish_requested.wait(0.2):
                            if self._cancelled.is_set():
                                return
                        if self._cancelled.is_set():
                            return
                        header = build_cookie_header(context.cookies([BILIBILI_HOME_URL]))
                        if not has_bilibili_login_cookie(header):
                            self._on_error('未检测到 B站登录状态。请在打开的窗口完成登录后再点击“完成登录”。')
                            return
                        save_bilibili_cookie(header)
                        self._on_success()
                    finally:
                        context.close()
        except Exception:
            self._on_error('无法完成 B站授权。请检查网络后重试。')
