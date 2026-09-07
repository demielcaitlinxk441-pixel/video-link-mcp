"""Local, user-visible Douyin authorization for audio-capable downloads."""

from __future__ import annotations

import threading
from collections.abc import Callable
from tempfile import TemporaryDirectory

from .local_credentials import save_douyin_cookie
from .yuanbao_authorization import build_cookie_header

DOUYIN_HOME_URL = 'https://www.douyin.com/'


def has_douyin_session_cookie(cookie_header: str) -> bool:
    """Require a session marker, rather than anonymous preferences only."""
    names = {
        part.strip().split('=', 1)[0]
        for part in (cookie_header or '').split(';')
        if '=' in part
    }
    return bool(names & {'sessionid', 'sessionid_ss'})


class DouyinAuthorizationSession:
    """Open a visible browser, then save only the confirmed local session."""

    def __init__(self, on_opened: Callable[[], None], on_success: Callable[[], None],
                 on_error: Callable[[str], None]) -> None:
        self._on_opened = on_opened
        self._on_success = on_success
        self._on_error = on_error
        self._finish_requested = threading.Event()
        self._cancelled = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name='douyin-authorization').start()

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
            with TemporaryDirectory(prefix='video-download-douyin-') as profile_dir:
                with sync_playwright() as playwright:
                    try:
                        context = playwright.chromium.launch_persistent_context(profile_dir, channel='chrome', headless=False)
                    except Exception:
                        context = playwright.chromium.launch_persistent_context(profile_dir, headless=False)
                    try:
                        page = context.pages[0] if context.pages else context.new_page()
                        page.goto(DOUYIN_HOME_URL, wait_until='domcontentloaded', timeout=60_000)
                        self._on_opened()
                        while not self._finish_requested.wait(0.2):
                            if self._cancelled.is_set():
                                return
                        if self._cancelled.is_set():
                            return
                        header = build_cookie_header(context.cookies([DOUYIN_HOME_URL]))
                        if not has_douyin_session_cookie(header):
                            self._on_error('未检测到抖音登录状态。请在打开的窗口完成登录后再点击“完成登录”。')
                            return
                        save_douyin_cookie(header)
                        self._on_success()
                    finally:
                        context.close()
        except Exception:
            self._on_error('无法完成抖音授权。请检查网络后重试。')
