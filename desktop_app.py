"""Native Windows desktop video downloader."""

import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QProgressBar, QMenu,
    QVBoxLayout, QWidget, QFileDialog, QScrollArea, QPlainTextEdit, QSizePolicy,
    QDialog, QDialogButtonBox, QLineEdit,
)

from lib.downloader import _is_kuaishou, download_video, retry_audio, retry_subtitle

ROOT = Path(__file__).resolve().parent
APP_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'VideoLinkAnalyzer'
HISTORY_FILE = APP_DIR / 'history.json'
SETTINGS_FILE = APP_DIR / 'settings.json'
QUEUE_FILE = APP_DIR / 'queue.json'
def _history() -> list[dict]:
    try:
        return json.loads(HISTORY_FILE.read_text(encoding='utf-8'))[:20]
    except (OSError, json.JSONDecodeError):
        return []


def _save_history(item: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps([item, *_history()][:20], ensure_ascii=False, indent=2), encoding='utf-8')


def _load_queue() -> list[dict]:
    try:
        value = json.loads(QUEUE_FILE.read_text(encoding='utf-8'))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_queue(items: list[dict]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')


def _update_history_entry(entry_id: str, updates: dict) -> None:
    entries = _history()
    for entry in entries:
        if entry.get('id') == entry_id:
            entry.update(updates)
            break
    APP_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')


def _remove_history_entry(entry_id: str) -> None:
    """Remove one local list record without touching the downloaded video."""
    remaining = [entry for entry in _history() if entry.get('id') != entry_id]
    APP_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(remaining, ensure_ascii=False, indent=2), encoding='utf-8')


def _settings() -> dict:
    try:
        value = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_settings(settings: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False), encoding='utf-8')


def _human_size(value: int | None) -> str:
    if not value:
        return ''
    if value >= 1024 ** 3:
        return f'{value / 1024 ** 3:.2f} GB'
    return f'{value / 1024 ** 2:.1f} MB'


def _failure_display(result: dict) -> str:
    failure = result.get('failure') or {}
    reason = failure.get('reason') or result.get('error', '无法下载该链接')
    action = failure.get('suggested_action') or '请稍后重试。'
    video_path = result.get('video_path') or (result.get('artifacts') or {}).get('video_path')
    completed = '画面已保存。' if video_path and Path(video_path).is_file() else '尚未生成可用媒体文件。'
    return f'问题原因：{reason} 已完成内容：{completed} 处理办法：{action}'


class DownloadEvents(QObject):
    progress = Signal(str, dict)
    finished = Signal(str, dict)


class AuthorizationEvents(QObject):
    opened = Signal()
    success = Signal()
    error = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        settings = _settings()
        self.events = DownloadEvents()
        self.events.progress.connect(self._update_progress)
        self.events.finished.connect(self._finished)
        self.jobs: dict[str, dict] = {}
        self.job_order: list[str] = []
        self.pending_job_ids: list[str] = []
        self.active_job_ids: set[str] = set()
        self.cancel_events: dict[str, threading.Event] = {}
        self._last_queue_persist = 0.0
        self._last_queue_signature = None
        self.authorization_session = None
        self.paused = False
        self.max_parallel_downloads = 2
        configured_download_dir = settings.get('download_dir')
        self.output_dir = Path(configured_download_dir).expanduser() if configured_download_dir else Path.home() / 'Downloads'
        self.setWindowTitle('视频下载')
        self.setMinimumSize(980, 680)
        self.resize(1180, 760)
        icon = ROOT / 'assets' / 'video-download-round.ico'
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self._build()
        self._restore_jobs()
        self._render_jobs()
        self._load_history()
        if self.pending_job_ids:
            QTimer.singleShot(0, self._start_pending_jobs)

    def _restore_jobs(self) -> None:
        """Restore unfinished local jobs; interrupted active jobs become resumable."""
        for saved in _load_queue():
            if not isinstance(saved, dict) or not saved.get('id') or not saved.get('url'):
                continue
            if saved.get('status') == 'completed':
                continue
            job = dict(saved)
            if job.get('status') == 'active':
                job.update({'status': 'waiting', 'stage': '等待续传', 'progress': 0})
            job.setdefault('output_dir', str(self.output_dir))
            job.setdefault('attempts', 0)
            self.jobs[job['id']] = job
            self.job_order.append(job['id'])
            self.cancel_events[job['id']] = threading.Event()
            if job.get('status') == 'waiting':
                self.pending_job_ids.append(job['id'])

    def _persist_jobs(self) -> None:
        safe_keys = {
            'id', 'url', 'title', 'stage', 'status', 'progress', 'output_dir',
            'mode', 'video_path', 'history_id', 'attempts', 'video_id',
            'temporary_file', 'meta', 'result',
        }
        items = [
            {key: value for key, value in self.jobs[job_id].items() if key in safe_keys}
            for job_id in self.job_order if job_id in self.jobs
        ]
        signature = tuple((item.get('id'), item.get('status'), item.get('mode')) for item in items)
        now = time.monotonic()
        if signature == self._last_queue_signature and items and now - self._last_queue_persist < 0.5:
            return
        try:
            _save_queue(items)
            self._last_queue_signature = signature
            self._last_queue_persist = now
        except OSError:
            pass

    def _build(self):
        root = QWidget(); root.setObjectName('root'); self.setCentralWidget(root)
        layout = QVBoxLayout(root); layout.setContentsMargins(48, 42, 48, 36); layout.setSpacing(26)
        card = QFrame(); card.setObjectName('inputCard'); card_layout = QHBoxLayout(card); card_layout.setContentsMargins(20, 18, 16, 18); card_layout.setSpacing(14)
        link = QLabel('⌁'); link.setObjectName('linkIcon'); card_layout.addWidget(link)
        self.url = QPlainTextEdit(); self.url.setObjectName('urlInput'); self.url.setPlaceholderText('粘贴视频链接；多个链接请每行一个'); self.url.setFixedHeight(76); card_layout.addWidget(self.url, 1)
        self.button = QPushButton('加入下载队列'); self.button.clicked.connect(self.start_download); self.button.setObjectName('downloadButton'); card_layout.addWidget(self.button)
        layout.addWidget(card)
        destination = QHBoxLayout(); destination.setSpacing(10)
        label = QLabel('下载位置'); label.setObjectName('destinationLabel'); destination.addWidget(label)
        self.destination_path = QLabel(); self.destination_path.setObjectName('destinationPath'); self.destination_path.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed); destination.addWidget(self.destination_path, 1)
        self.folder_button = QPushButton('选择位置'); self.folder_button.setObjectName('folderButton'); self.folder_button.clicked.connect(self.choose_folder); destination.addWidget(self.folder_button)
        self.authorization_button = QPushButton('视频号授权'); self.authorization_button.setObjectName('authorizationButton'); self.authorization_button.clicked.connect(self.show_wechat_authorization); destination.addWidget(self.authorization_button)
        self.bilibili_authorization_button = QPushButton('B站授权'); self.bilibili_authorization_button.setObjectName('authorizationButton'); self.bilibili_authorization_button.setToolTip('使用本人 B站登录状态下载 B站视频'); self.bilibili_authorization_button.clicked.connect(self.show_bilibili_authorization); destination.addWidget(self.bilibili_authorization_button)
        self.douyin_authorization_button = QPushButton('抖音授权'); self.douyin_authorization_button.setObjectName('authorizationButton'); self.douyin_authorization_button.setToolTip('使用本人抖音登录状态下载带音频的视频'); self.douyin_authorization_button.clicked.connect(self.show_douyin_authorization); destination.addWidget(self.douyin_authorization_button)
        layout.addLayout(destination)
        self._refresh_destination()
        self.hint = QLabel(); self.hint.setObjectName('hint'); self.hint.hide(); layout.addWidget(self.hint)
        columns = QHBoxLayout(); columns.setContentsMargins(0, 0, 0, 0); columns.setSpacing(24)
        left = QVBoxLayout(); task_header = QHBoxLayout(); header = QLabel('下载队列'); header.setObjectName('sectionTitle'); self.queue_title = header; task_header.addWidget(header)
        self.queue_summary = QLabel(''); self.queue_summary.setObjectName('queueSummary'); task_header.addWidget(self.queue_summary, 1)
        self.pause_button = QPushButton('暂停队列'); self.pause_button.setObjectName('queueButton'); self.pause_button.setToolTip('正在下载的视频会继续完成；暂停后不会启动等待中的任务。'); self.pause_button.setFixedWidth(104); self.pause_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed); self.pause_button.clicked.connect(self.toggle_pause); task_header.addWidget(self.pause_button)
        left.addLayout(task_header)
        self.task_card = QFrame(); self.task_card.setObjectName('taskCard'); self.task_card.setMinimumHeight(190); task = QVBoxLayout(self.task_card); task.setContentsMargins(12, 12, 12, 12); task.setSpacing(8)
        self.task_scroll = QScrollArea(); self.task_scroll.setObjectName('taskScroll'); self.task_scroll.setWidgetResizable(True); self.task_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.task_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.task_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.task_scroll.viewport().setObjectName('taskViewport')
        self.task_list_widget = QWidget(); self.task_list_widget.setObjectName('taskList'); self.task_list_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.task_list = QVBoxLayout(self.task_list_widget); self.task_list.setContentsMargins(0, 0, 0, 0); self.task_list.setSpacing(10); self.task_list.addStretch()
        self.task_scroll.setWidget(self.task_list_widget); task.addWidget(self.task_scroll); left.addWidget(self.task_card)
        self.task_card.hide()
        self.empty_queue = QLabel('暂无下载任务\n粘贴视频链接后开始下载')
        self.empty_queue.setObjectName('emptyState')
        self.empty_queue.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_queue.setMinimumHeight(118)
        left.addWidget(self.empty_queue)
        right = QVBoxLayout(); history_title = QLabel('最近下载'); history_title.setObjectName('sectionTitle'); right.addWidget(history_title)
        self.history = QListWidget(); self.history.setMinimumHeight(190); self.history.setObjectName('history'); self.history.itemDoubleClicked.connect(self.open_file); self.history.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.history.customContextMenuRequested.connect(self.show_history_menu); right.addWidget(self.history)
        left_panel = QFrame(); left_panel.setObjectName('sectionPanel'); left_panel_layout = QVBoxLayout(left_panel); left_panel_layout.setContentsMargins(18, 16, 18, 18); left_panel_layout.setSpacing(12); left_panel_layout.addLayout(left)
        right_panel = QFrame(); right_panel.setObjectName('sectionPanel'); right_panel_layout = QVBoxLayout(right_panel); right_panel_layout.setContentsMargins(18, 16, 18, 18); right_panel_layout.setSpacing(12); right_panel_layout.addLayout(right)
        columns.addWidget(left_panel, 3); columns.addWidget(right_panel, 2)
        columns.setAlignment(left, Qt.AlignmentFlag.AlignTop)
        columns.setAlignment(right, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(columns); layout.addStretch(1)
    def _refresh_destination(self):
        self.destination_path.setText(str(self.output_dir))
        self.destination_path.setToolTip(f'视频下载位置：{self.output_dir}')

    def choose_folder(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            '选择下载位置',
            str(self.output_dir if self.output_dir.exists() else Path.home()),
        )
        if not directory:
            return
        selected_dir = Path(directory)
        try:
            selected_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._show_hint(f'无法使用该下载位置：{exc}', error=True)
            return
        self.output_dir = selected_dir
        self._refresh_destination()
        settings = _settings()
        settings.pop('knowledge_vault', None)
        settings.pop('ai', None)
        settings['download_dir'] = str(self.output_dir)
        try:
            _save_settings(settings)
        except OSError:
            self._show_hint('位置已切换，但无法保存设置；本次运行仍会使用新位置。', error=True)
            return
        self._show_hint(f'下载位置已设置为：{self.output_dir}')

    def _show_hint(self, message: str, *, error: bool = False) -> None:
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        self.hint.setWordWrap(True)
        self.hint.setText(message)
        self.hint.setObjectName('error' if error else 'hint')
        self.hint.show()
        self.hint.style().unpolish(self.hint)
        self.hint.style().polish(self.hint)

    def show_wechat_authorization(self):
        """Store the owner's Yuanbao credential locally with Windows encryption."""
        from lib.local_credentials import clear_yuanbao_cookie, get_yuanbao_cookie, save_yuanbao_cookie

        dialog = QDialog(self)
        dialog.setWindowTitle('视频号授权')
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        heading = QLabel('使用本人授权账号解析视频号链接')
        heading.setObjectName('authorizationTitle')
        layout.addWidget(heading)
        explanation = QLabel('一键授权会打开独立的元宝登录窗口。你自己登录后，程序只将本次授权加密保存在本机。')
        explanation.setWordWrap(True)
        explanation.setObjectName('authorizationHelp')
        layout.addWidget(explanation)
        reauthorize_button = QPushButton('一键重新授权')
        reauthorize_button.setObjectName('reauthorizeButton')
        reauthorize_button.setAccessibleName('一键重新授权')
        layout.addWidget(reauthorize_button, alignment=Qt.AlignmentFlag.AlignLeft)
        finish_button = QPushButton('完成登录')
        finish_button.setObjectName('authorizationButton')
        finish_button.setEnabled(False)
        finish_button.hide()
        layout.addWidget(finish_button, alignment=Qt.AlignmentFlag.AlignLeft)
        manual_button = QPushButton('手动输入 Cookie')
        manual_button.setObjectName('manualAuthorizationButton')
        layout.addWidget(manual_button, alignment=Qt.AlignmentFlag.AlignLeft)
        label = QLabel('元宝 Cookie')
        label.hide()
        layout.addWidget(label)
        cookie_input = QLineEdit()
        cookie_input.setObjectName('authorizationInput')
        cookie_input.setEchoMode(QLineEdit.EchoMode.Password)
        cookie_input.setPlaceholderText('粘贴后点击保存')
        cookie_input.setAccessibleName('元宝 Cookie')
        cookie_input.hide()
        layout.addWidget(cookie_input)
        configured = bool(get_yuanbao_cookie())
        state = QLabel('当前状态：已配置本机授权' if configured else '当前状态：未配置本机授权')
        state.setObjectName('authorizationState')
        layout.addWidget(state)
        clear_button = QPushButton('清除本机授权')
        clear_button.setObjectName('removeJobButton')
        clear_button.setEnabled(configured)
        layout.addWidget(clear_button, alignment=Qt.AlignmentFlag.AlignLeft)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存授权')
        buttons.button(QDialogButtonBox.StandardButton.Save).hide()
        buttons.accepted.connect(lambda: self._save_wechat_authorization(cookie_input, dialog))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def clear_authorization():
            clear_yuanbao_cookie()
            state.setText('当前状态：未配置本机授权')
            clear_button.setEnabled(False)
            self._show_hint('已清除本机视频号授权。')

        clear_button.clicked.connect(clear_authorization)
        manual_button.clicked.connect(lambda: (
            label.setVisible(not label.isVisible()),
            cookie_input.setVisible(not cookie_input.isVisible()),
            buttons.button(QDialogButtonBox.StandardButton.Save).setVisible(
                cookie_input.isVisible()
            ),
            manual_button.setText('收起手动输入' if cookie_input.isVisible() else '手动输入 Cookie'),
        ))

        auth_events = AuthorizationEvents(dialog)

        def begin_reauthorization():
            from lib.yuanbao_authorization import YuanbaoAuthorizationSession

            reauthorize_button.setEnabled(False)
            state.setText('正在打开元宝登录窗口…')
            self.authorization_session = YuanbaoAuthorizationSession(
                auth_events.opened.emit, auth_events.success.emit, auth_events.error.emit
            )
            self.authorization_session.start()

        def authorization_opened():
            state.setText('已打开元宝。完成本人登录后，回到这里点击“完成登录”。')
            finish_button.show()
            finish_button.setEnabled(True)

        def finish_reauthorization():
            finish_button.setEnabled(False)
            state.setText('正在保存本机授权…')
            if self.authorization_session:
                self.authorization_session.finish_login()

        def authorization_success():
            self.authorization_session = None
            self._show_hint('本机视频号授权已更新。之后的视频号链接将优先使用你的账号解析。')
            dialog.accept()

        def authorization_error(message: str):
            self.authorization_session = None
            reauthorize_button.setEnabled(True)
            finish_button.hide()
            state.setText(message)
            state.setObjectName('authorizationError')
            state.style().unpolish(state)
            state.style().polish(state)

        auth_events.opened.connect(authorization_opened)
        auth_events.success.connect(authorization_success)
        auth_events.error.connect(authorization_error)
        reauthorize_button.clicked.connect(begin_reauthorization)
        finish_button.clicked.connect(finish_reauthorization)
        dialog.rejected.connect(lambda: self.authorization_session.cancel() if self.authorization_session else None)
        dialog.exec()

    def show_bilibili_authorization(self):
        """Save the owner's Bilibili session in Windows-encrypted local storage."""
        from lib.local_credentials import clear_bilibili_cookie, get_bilibili_cookie

        dialog = QDialog(self)
        dialog.setWindowTitle('B站授权')
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        heading = QLabel('使用本人 B站账号下载视频')
        heading.setObjectName('authorizationTitle')
        layout.addWidget(heading)
        explanation = QLabel('点击授权后会打开独立 B站窗口。你自己完成登录后，回到这里点击“完成登录”。程序只将 B站授权加密保存在本机。')
        explanation.setWordWrap(True)
        explanation.setObjectName('authorizationHelp')
        layout.addWidget(explanation)
        start_button = QPushButton('开始 B站授权')
        start_button.setObjectName('reauthorizeButton')
        layout.addWidget(start_button, alignment=Qt.AlignmentFlag.AlignLeft)
        finish_button = QPushButton('完成登录')
        finish_button.setObjectName('authorizationButton')
        finish_button.setEnabled(False)
        finish_button.hide()
        layout.addWidget(finish_button, alignment=Qt.AlignmentFlag.AlignLeft)
        configured = bool(get_bilibili_cookie())
        state = QLabel('当前状态：已配置本机 B站授权' if configured else '当前状态：未配置本机 B站授权')
        state.setObjectName('authorizationState')
        layout.addWidget(state)
        clear_button = QPushButton('清除本机 B站授权')
        clear_button.setObjectName('removeJobButton')
        clear_button.setEnabled(configured)
        layout.addWidget(clear_button, alignment=Qt.AlignmentFlag.AlignLeft)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        auth_events = AuthorizationEvents(dialog)

        def start_authorization():
            from lib.bilibili_authorization import BilibiliAuthorizationSession
            start_button.setEnabled(False)
            state.setText('正在打开 B站登录窗口…')
            self.authorization_session = BilibiliAuthorizationSession(
                auth_events.opened.emit, auth_events.success.emit, auth_events.error.emit
            )
            self.authorization_session.start()

        def authorization_opened():
            state.setText('已打开 B站。完成本人登录后，回到这里点击“完成登录”。')
            finish_button.show()
            finish_button.setEnabled(True)

        def finish_authorization():
            finish_button.setEnabled(False)
            state.setText('正在保存本机 B站授权…')
            if self.authorization_session:
                self.authorization_session.finish_login()

        def authorization_success():
            self.authorization_session = None
            self._show_hint('本机 B站授权已更新。之后的 B站链接会优先使用你的账号下载。')
            dialog.accept()

        def authorization_error(message: str):
            self.authorization_session = None
            start_button.setEnabled(True)
            finish_button.hide()
            state.setText(message)
            state.setObjectName('authorizationError')
            state.style().unpolish(state)
            state.style().polish(state)

        def clear_authorization():
            clear_bilibili_cookie()
            state.setText('当前状态：未配置本机 B站授权')
            clear_button.setEnabled(False)
            self._show_hint('已清除本机 B站授权。')

        auth_events.opened.connect(authorization_opened)
        auth_events.success.connect(authorization_success)
        auth_events.error.connect(authorization_error)
        start_button.clicked.connect(start_authorization)
        finish_button.clicked.connect(finish_authorization)
        clear_button.clicked.connect(clear_authorization)
        dialog.rejected.connect(lambda: self.authorization_session.cancel() if self.authorization_session else None)
        dialog.exec()

    def show_douyin_authorization(self):
        """Save the owner's Douyin session for audio-capable downloads."""
        from lib.local_credentials import clear_douyin_cookie, get_douyin_cookie

        dialog = QDialog(self)
        dialog.setWindowTitle('抖音授权')
        dialog.setMinimumWidth(460)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        heading = QLabel('使用本人抖音账号下载带音频的视频')
        heading.setObjectName('authorizationTitle')
        layout.addWidget(heading)
        explanation = QLabel('点击授权后会打开独立抖音窗口。你自己完成登录后，回到这里点击“完成登录”。程序只将抖音授权加密保存在本机。')
        explanation.setWordWrap(True)
        explanation.setObjectName('authorizationHelp')
        layout.addWidget(explanation)
        start_button = QPushButton('开始抖音授权')
        start_button.setObjectName('reauthorizeButton')
        layout.addWidget(start_button, alignment=Qt.AlignmentFlag.AlignLeft)
        finish_button = QPushButton('完成登录')
        finish_button.setObjectName('authorizationButton')
        finish_button.setEnabled(False)
        finish_button.hide()
        layout.addWidget(finish_button, alignment=Qt.AlignmentFlag.AlignLeft)
        configured = bool(get_douyin_cookie())
        state = QLabel('当前状态：已配置本机抖音授权' if configured else '当前状态：未配置本机抖音授权')
        state.setObjectName('authorizationState')
        layout.addWidget(state)
        clear_button = QPushButton('清除本机抖音授权')
        clear_button.setObjectName('removeJobButton')
        clear_button.setEnabled(configured)
        layout.addWidget(clear_button, alignment=Qt.AlignmentFlag.AlignLeft)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        auth_events = AuthorizationEvents(dialog)

        def start_authorization():
            from lib.douyin_authorization import DouyinAuthorizationSession
            start_button.setEnabled(False)
            state.setText('正在打开抖音登录窗口…')
            self.authorization_session = DouyinAuthorizationSession(
                auth_events.opened.emit, auth_events.success.emit, auth_events.error.emit
            )
            self.authorization_session.start()

        def authorization_opened():
            state.setText('已打开抖音。完成本人登录后，回到这里点击“完成登录”。')
            finish_button.show()
            finish_button.setEnabled(True)

        def finish_authorization():
            finish_button.setEnabled(False)
            state.setText('正在保存本机抖音授权…')
            if self.authorization_session:
                self.authorization_session.finish_login()

        def authorization_success():
            self.authorization_session = None
            self._show_hint('本机抖音授权已更新。抖音下载会优先尝试带音频版本。')
            dialog.accept()

        def authorization_error(message: str):
            self.authorization_session = None
            start_button.setEnabled(True)
            finish_button.hide()
            state.setText(message)
            state.setObjectName('authorizationError')
            state.style().unpolish(state)
            state.style().polish(state)

        def clear_authorization():
            clear_douyin_cookie()
            state.setText('当前状态：未配置本机抖音授权')
            clear_button.setEnabled(False)
            self._show_hint('已清除本机抖音授权。')

        auth_events.opened.connect(authorization_opened)
        auth_events.success.connect(authorization_success)
        auth_events.error.connect(authorization_error)
        start_button.clicked.connect(start_authorization)
        finish_button.clicked.connect(finish_authorization)
        clear_button.clicked.connect(clear_authorization)
        dialog.rejected.connect(lambda: self.authorization_session.cancel() if self.authorization_session else None)
        dialog.exec()

    def _save_wechat_authorization(self, cookie_input: QLineEdit, dialog: QDialog):
        from lib.local_credentials import save_yuanbao_cookie
        try:
            save_yuanbao_cookie(cookie_input.text())
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.warning(dialog, '无法保存授权', str(exc))
            return
        self._show_hint('本机视频号授权已保存。之后的视频号链接将优先使用你的账号解析。')
        dialog.accept()

    @staticmethod
    def _extract_urls(text: str) -> list[str]:
        """Accept one URL per line, while also tolerating copied share text."""
        urls: list[str] = []
        for url in re.findall(r'https?://[^\s，。；、！？，（）【】《》]+', text):
            url = url.rstrip('，。；,.;!！?？）)]}》')
            if url not in urls:
                urls.append(url)
        return urls

    @staticmethod
    def _is_kuaishou_url(url: str) -> bool:
        return _is_kuaishou(url)

    def _show_kuaishou_notice(self) -> bool:
        """Explain the required user action before the Kuaishou browser opens."""
        notice = QMessageBox(self)
        notice.setIcon(QMessageBox.Icon.Information)
        notice.setWindowTitle('快手下载提示')
        notice.setText('快手需要你手动点击一次“点击重试”')
        notice.setInformativeText(
            '点击“我知道了，继续”后会打开快手窗口。\n\n'
            '如果看到“浏览器版本过低”，请在快手窗口点击“点击重试”，然后保持该窗口打开；下载器会继续自动下载视频。'
        )
        notice.setStandardButtons(
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )
        notice.button(QMessageBox.StandardButton.Ok).setText('我知道了，继续')
        notice.button(QMessageBox.StandardButton.Cancel).setText('暂不下载')
        notice.setDefaultButton(QMessageBox.StandardButton.Ok)
        return notice.exec() == QMessageBox.StandardButton.Ok

    def start_download(self):
        urls = self._extract_urls(self.url.toPlainText())
        if not urls:
            self._show_hint('请粘贴完整的视频链接；多个链接请每行一个。', error=True)
            return
        if any(self._is_kuaishou_url(url) for url in urls) and not self._show_kuaishou_notice():
            self._show_hint('已取消快手下载，链接仍保留在输入框中。')
            return
        # Failed rows should not block a retry of the same link.
        retry_urls = set(urls)
        failed_ids = [
            job_id for job_id, job in self.jobs.items()
            if job.get('status') == 'failed' and job.get('url') in retry_urls
        ]
        for job_id in failed_ids:
            self.jobs.pop(job_id, None)
            self.cancel_events.pop(job_id, None)
            self.job_order = [item for item in self.job_order if item != job_id]
            self.pending_job_ids = [item for item in self.pending_job_ids if item != job_id]
        existing_urls = {
            job['url'] for job in self.jobs.values()
            if job.get('status') in {'waiting', 'active'}
        }
        completed_urls = {
            (entry.get('metadata') or {}).get('source_url')
            for entry in _history()
            if Path(entry.get('video_path', '')).is_file()
        }
        added = 0
        for url in urls:
            if url in existing_urls or url in completed_urls:
                continue
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {'id': job_id, 'url': url, 'title': url, 'stage': '等待下载', 'status': 'waiting', 'progress': 0, 'output_dir': str(self.output_dir)}
            self.cancel_events[job_id] = threading.Event()
            self.job_order.append(job_id); self.pending_job_ids.append(job_id); existing_urls.add(url); added += 1
        self.url.clear(); self.task_card.show(); self.empty_queue.hide(); self.hint.hide()
        self._start_pending_jobs()
        if added:
            self._show_hint(f'已加入 {added} 个链接，默认同时下载 {self.max_parallel_downloads} 个。')
        elif any(url in completed_urls for url in urls):
            self._show_hint('该链接已经下载完成，可在“最近下载”中打开。')
        else:
            self._show_hint('这些链接已经在下载队列中。')

    def _start_pending_jobs(self):
        while not self.paused and self.pending_job_ids and len(self.active_job_ids) < self.max_parallel_downloads:
            job_id = self.pending_job_ids.pop(0); job = self.jobs.get(job_id)
            if not job or job.get('status') != 'waiting':
                continue
            job.update({'status': 'active', 'stage': '正在解析链接', 'progress': None})
            self.active_job_ids.add(job_id)
            threading.Thread(target=self._download_worker, args=(job_id,), daemon=True).start()
        self._render_jobs()

    def _download_worker(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job:
            return
        last_report = 0.0
        last_stage = None
        def report(data):
            nonlocal last_report, last_stage
            now = time.monotonic()
            stage = data.get('stage')
            if stage != last_stage or now - last_report >= 0.2:
                last_report, last_stage = now, stage
                self.events.progress.emit(job_id, data)
        try:
            output_dir = Path(job['output_dir']); output_dir.mkdir(parents=True, exist_ok=True)
            if job.get('mode') == 'retry_audio':
                result = retry_audio(
                    job['url'], job['video_path'],
                    progress_callback=report,
                    cancel_callback=self.cancel_events[job_id].is_set,
                )
            elif job.get('mode') == 'retry_subtitle':
                result = retry_subtitle(
                    job['url'], job['output_dir'],
                    progress_callback=report,
                    cancel_callback=self.cancel_events[job_id].is_set,
                )
            else:
                result = download_video(
                    job['url'], str(output_dir),
                    progress_callback=report,
                    cancel_callback=self.cancel_events[job_id].is_set,
                )
        except Exception as exc:
            from lib.download_diagnostics import normalize_result
            result = normalize_result({'success': False, 'error': f'无法保存或下载视频：{exc}'})
        self.events.finished.emit(job_id, result)

    def _update_progress(self, job_id: str, data: dict):
        job = self.jobs.get(job_id)
        if not job:
            return
        job['stage'] = data.get('stage', '正在下载')
        if 'progress' in data:
            job['progress'] = int(data['progress']) if data['progress'] is not None else None
        if data.get('attempt'):
            job['attempts'] = int(data['attempt'])
        if data.get('temporary_file'):
            job['temporary_file'] = data['temporary_file']
        self._render_jobs()

    def _finished(self, job_id: str, result: dict):
        job = self.jobs.get(job_id); self.active_job_ids.discard(job_id)
        self.cancel_events.pop(job_id, None)
        if not job:
            self._start_pending_jobs(); return
        if job.get('mode') == 'retry_audio':
            self._finish_audio_retry(job_id, job, result)
            return
        if job.get('mode') == 'retry_subtitle':
            self._finish_subtitle_retry(job_id, job, result)
            return
        if result.get('cancelled'):
            self.jobs.pop(job_id, None)
            self.job_order = [item for item in self.job_order if item != job_id]
            self.pending_job_ids = [item for item in self.pending_job_ids if item != job_id]
            self._show_hint('下载已取消。')
            self._render_jobs(); self._start_pending_jobs(); return
        if not result.get('success'):
            failure = result.get('failure') or {}
            message = _failure_display(result)
            job.update({
                'status': 'failed',
                'stage': f"{failure.get('failed_stage') or '下载'}失败",
                'progress': 0,
                'meta': message,
                'result': result,
            })
            self._show_hint(message, error=True)
            self._render_jobs(); self._start_pending_jobs(); return
        metadata = dict(result.get('metadata') or {}); title = metadata.get('title') or Path(result['video_path']).stem
        metadata['source_url'] = job.get('url', '')
        metadata['subtitle_status'] = result.get('subtitle_status', 'unavailable')
        compatibility = result.get('compatibility') or {}; compatibility_status = compatibility.get('status')
        if compatibility_status == 'missing_audio':
            metadata['audio_status'] = 'missing'
            job.update({'stage': '下载完成（无音频）', 'meta': f"已保存（无音频） · {_human_size(result.get('size'))}"})
            self._show_hint('视频已保存，但未检测到音轨。')
        elif compatibility_status in {'conversion_unavailable', 'conversion_failed'}:
            self._show_hint('视频已保存，但兼容性检查没有完成；请确认已安装 ffmpeg。', error=True)
        else:
            job.update({'stage': '下载完成', 'meta': f"已保存 · {_human_size(result.get('size'))}"})
        try:
            _save_history({
                'id': uuid.uuid4().hex,
                'title': title,
                'video_path': result['video_path'],
                'size': result.get('size', 0),
                'created_at': int(time.time()),
                'metadata': metadata,
                'subtitle_text': (result.get('subtitle_text') or '')[:12000],
                'subtitle_path': result.get('subtitle_path'),
            })
            self._load_history()
        except OSError:
            self._show_hint('视频已下载，但系统无法保存下载记录。', error=True)
        # 成功下载后的文件已出现在“最近下载”中，不再占用下载队列。
        self.job_order = [item for item in self.job_order if item != job_id]
        self.pending_job_ids = [item for item in self.pending_job_ids if item != job_id]
        self.jobs.pop(job_id, None)
        if not self.jobs:
            self.task_card.hide()
            self.empty_queue.show()
        self._render_jobs(); self._start_pending_jobs()

    def _render_jobs(self):
        self.task_card.setVisible(bool(self.jobs))
        self.empty_queue.setVisible(not self.jobs)
        while self.task_list.count():
            item = self.task_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        active = len(self.active_job_ids)
        waiting = sum(job.get('status') == 'waiting' for job in self.jobs.values())
        failed = sum(job.get('status') == 'failed' for job in self.jobs.values())
        if self.paused and not waiting:
            # 没有等待中的任务时，暂停状态已不再有意义；避免留下无法恢复的状态。
            self.paused = False
            self.hint.clear()
            self.hint.hide()
        summary = [f'{active} 个下载中', f'{waiting} 个等待']
        if failed:
            summary.append(f'{failed} 个失败')
        if self.jobs:
            self.queue_summary.setText(' · '.join(summary))
            self.queue_summary.show()
        else:
            self.queue_summary.clear()
            self.queue_summary.hide()
        self.pause_button.setText('继续队列' if self.paused else '暂停队列')
        self.pause_button.setEnabled(bool(waiting))
        for job_id in self.job_order:
            job = self.jobs.get(job_id)
            if job:
                self.task_list.addWidget(self._job_row(job))
        self.task_list.addStretch()
        self._persist_jobs()

    def _job_row(self, job: dict) -> QFrame:
        row = QFrame(); row.setObjectName('jobRow')
        content = QVBoxLayout(row); content.setContentsMargins(16, 14, 16, 14); content.setSpacing(10)
        title = QLabel(job.get('title', job['url'])); title.setObjectName('jobTitle'); title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setToolTip(job.get('title', job['url']))
        content.addWidget(title)
        stage_label = QLabel(job.get('stage') or '等待下载')
        stage_label.setObjectName('jobStage'); stage_label.setWordWrap(True)
        content.addWidget(stage_label)
        if job.get('status') == 'failed' and job.get('meta'):
            detail = QLabel(job['meta']); detail.setObjectName('jobMeta')
            detail.setTextFormat(Qt.TextFormat.PlainText)
            detail.setWordWrap(True); detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            content.addWidget(detail)
        progress = QProgressBar()
        current_progress = job.get('progress')
        is_active = job.get('status') == 'active'
        if is_active and current_progress is None:
            # An indeterminate bar makes parsing, verification and waiting
            # states visibly active instead of looking like a frozen task.
            progress.setRange(0, 0)
            progress.setTextVisible(True)
            progress.setFormat(job.get('stage') or '正在处理')
        else:
            progress.setRange(0, 100)
            progress.setValue(int(current_progress or 0))
            is_downloading = job.get('stage') in {'正在下载', '正在下载视频'}
            progress.setTextVisible(is_downloading and current_progress is not None)
            if progress.isTextVisible():
                progress.setFormat('下载中 %p%')
        content.addWidget(progress)
        cancel = QPushButton('取消')
        cancel.setObjectName('removeJobButton')
        cancel.clicked.connect(lambda _checked=False, job_id=job['id']: self.cancel_job(job_id))
        if job.get('status') == 'failed' and job.get('result'):
            retry_button = QPushButton('重试'); retry_button.setObjectName('jobButton')
            retry_button.clicked.connect(lambda _checked=False, job_id=job['id']: self.retry_job(job_id))
            content.addWidget(retry_button, 0, Qt.AlignmentFlag.AlignRight)
            report_button = QPushButton('复制诊断')
            report_button.setObjectName('jobButton')
            report_button.setAccessibleName('复制下载诊断报告')
            report_button.clicked.connect(
                lambda _checked=False, job_id=job['id']: self.copy_job_diagnostics(job_id)
            )
            content.addWidget(report_button, 0, Qt.AlignmentFlag.AlignRight)
            cancel.setText('移除任务')
            content.addWidget(cancel, 0, Qt.AlignmentFlag.AlignRight)
        else:
            content.addWidget(cancel, 0, Qt.AlignmentFlag.AlignRight)
        return row

    def copy_job_diagnostics(self, job_id: str) -> None:
        from lib.download_diagnostics import diagnostic_report

        job = self.jobs.get(job_id) or {}
        result = job.get('result') or {}
        QApplication.clipboard().setText(diagnostic_report(result))
        self._show_hint('诊断报告已复制，敏感信息已隐藏。')

    def retry_job(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job or job.get('status') != 'failed':
            return
        job.update(status='waiting', stage='等待重试', progress=0, meta='')
        job.pop('result', None)
        self.cancel_events[job_id] = threading.Event()
        if job_id not in self.pending_job_ids:
            self.pending_job_ids.append(job_id)
        self._start_pending_jobs()

    def cancel_job(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        event = self.cancel_events.get(job_id)
        if event:
            event.set()
        if job.get('status') in {'waiting', 'failed'}:
            self.jobs.pop(job_id, None)
            self.cancel_events.pop(job_id, None)
            self.job_order = [item for item in self.job_order if item != job_id]
            self.pending_job_ids = [item for item in self.pending_job_ids if item != job_id]
            self._render_jobs()
            self._show_hint('任务已移除，已保存文件保留。')
        else:
            job['stage'] = '正在取消'
            self._render_jobs()

    def toggle_pause(self):
        if not any(job.get('status') == 'waiting' for job in self.jobs.values()):
            self.paused = False
            self._render_jobs()
            return
        self.paused = not self.paused
        if self.paused:
            self._render_jobs()
            self._show_hint('已暂停队列；正在下载的视频会继续完成。')
        else:
            self.hint.clear()
            self.hint.hide()
            self._start_pending_jobs()

    def _load_history(self):
        self.history.clear()
        for entry in _history():
            if (entry.get('metadata') or {}).get('audio_status') == 'missing':
                status = '画面已保存，音频获取失败 · 右键重试音频'
            elif (entry.get('metadata') or {}).get('subtitle_status') == 'failed':
                status = '视频完成／字幕失败 · 右键重试字幕'
            elif (entry.get('metadata') or {}).get('subtitle_status') == 'unavailable':
                status = '下载完成 · 暂无可用字幕'
            else:
                status = '下载完成'
            item = QListWidgetItem(f"{entry['title']}\n{_human_size(entry.get('size'))}   ·   双击打开 · {status}")
            item.setData(Qt.ItemDataRole.UserRole, entry); self.history.addItem(item)

    def _current_history_entry(self) -> dict | None:
        item = self.history.currentItem()
        entry = item.data(Qt.ItemDataRole.UserRole) if item else None
        return entry if isinstance(entry, dict) and entry.get('id') else None

    def show_history_menu(self, point):
        item = self.history.itemAt(point)
        if not item:
            return
        self.history.setCurrentItem(item)
        menu = QMenu(self)
        open_folder = menu.addAction('打开视频所在文件夹')
        entry = item.data(Qt.ItemDataRole.UserRole)
        audio_missing = isinstance(entry, dict) and (entry.get('metadata') or {}).get('audio_status') == 'missing'
        retry_audio_action = menu.addAction('重试音频') if audio_missing else None
        subtitle_failed = isinstance(entry, dict) and (entry.get('metadata') or {}).get('subtitle_status') in {'failed', 'unavailable'}
        retry_subtitle_action = menu.addAction('重试字幕') if subtitle_failed else None
        menu.addSeparator()
        delete_file = menu.addAction('删除记录和视频文件')
        selected = menu.exec(self.history.viewport().mapToGlobal(point))
        if selected == open_folder:
            self.open_history_folder()
        elif retry_audio_action is not None and selected == retry_audio_action:
            self.retry_history_audio()
        elif retry_subtitle_action is not None and selected == retry_subtitle_action:
            self.retry_history_subtitle()
        elif selected == delete_file:
            self.delete_history_with_file()

    def retry_history_audio(self) -> None:
        entry = self._current_history_entry()
        if not entry:
            return
        video_path = Path(entry.get('video_path', ''))
        source_url = (entry.get('metadata') or {}).get('source_url') or (entry.get('metadata') or {}).get('webpage_url')
        if not video_path.is_file():
            self._show_hint('已保存的画面文件不存在，无法补音频。', error=True)
            return
        if not source_url:
            self._show_hint('旧记录没有来源链接，无法单独补音频。', error=True)
            return
        job_id = uuid.uuid4().hex
        self.jobs[job_id] = {
            'id': job_id, 'url': source_url, 'title': entry.get('title', source_url),
            'stage': '等待补音频', 'status': 'waiting', 'progress': 0,
            'output_dir': str(video_path.parent), 'video_path': str(video_path),
            'history_id': entry['id'], 'mode': 'retry_audio',
        }
        self.cancel_events[job_id] = threading.Event()
        self.job_order.append(job_id); self.pending_job_ids.append(job_id)
        self.task_card.show(); self.empty_queue.hide()
        self._show_hint('已加入音频重试，只会获取音频，不会重复下载画面。')
        self._start_pending_jobs()

    def _finish_audio_retry(self, job_id: str, job: dict, result: dict) -> None:
        if result.get('cancelled'):
            self.jobs.pop(job_id, None)
            self.job_order = [item for item in self.job_order if item != job_id]
            self._show_hint('音频重试已取消。')
        elif result.get('success'):
            entries = _history()
            current = next((item for item in entries if item.get('id') == job.get('history_id')), {})
            metadata = dict(current.get('metadata') or {})
            metadata['audio_status'] = 'present'
            _update_history_entry(job['history_id'], {
                'metadata': metadata, 'size': result.get('size', current.get('size', 0))
            })
            self.jobs.pop(job_id, None)
            self.job_order = [item for item in self.job_order if item != job_id]
            self._load_history()
            self._show_hint('音频已补全，画面没有重复下载。')
        else:
            failure = result.get('failure') or {}
            job.update({
                'status': 'failed', 'stage': '音频下载失败', 'progress': 0,
                'meta': f"{failure.get('reason') or result.get('error', '补音频失败')} {failure.get('suggested_action') or ''}",
                'result': result,
            })
            self._show_hint(job['meta'], error=True)
        if not self.jobs:
            self.task_card.hide(); self.empty_queue.show()
        self._render_jobs(); self._start_pending_jobs()

    def retry_history_subtitle(self) -> None:
        entry = self._current_history_entry()
        if not entry:
            return
        video_path = Path(entry.get('video_path', ''))
        source_url = (entry.get('metadata') or {}).get('source_url') or (entry.get('metadata') or {}).get('webpage_url')
        if not video_path.is_file() or not source_url:
            self._show_hint('视频文件或来源链接不存在，无法重试字幕。', error=True)
            return
        job_id = uuid.uuid4().hex
        self.jobs[job_id] = {
            'id': job_id, 'url': source_url, 'title': entry.get('title', source_url),
            'stage': '等待补字幕', 'status': 'waiting', 'progress': 0,
            'output_dir': str(video_path.parent), 'video_path': str(video_path),
            'history_id': entry['id'], 'mode': 'retry_subtitle',
        }
        self.cancel_events[job_id] = threading.Event()
        self.job_order.append(job_id); self.pending_job_ids.append(job_id)
        self.task_card.show(); self.empty_queue.hide()
        self._show_hint('已加入字幕重试，不会重新下载视频或音频。')
        self._start_pending_jobs()

    def _finish_subtitle_retry(self, job_id: str, job: dict, result: dict) -> None:
        if result.get('success'):
            entries = _history()
            current = next((item for item in entries if item.get('id') == job.get('history_id')), {})
            metadata = dict(current.get('metadata') or {})
            metadata['subtitle_status'] = 'completed'
            _update_history_entry(job['history_id'], {
                'metadata': metadata,
                'subtitle_path': result.get('subtitle_path'),
                'subtitle_text': (result.get('subtitle_text') or '')[:12000],
            })
            self.jobs.pop(job_id, None)
            self.job_order = [item for item in self.job_order if item != job_id]
            self._load_history()
            self._show_hint('字幕已补全，媒体文件没有重复下载。')
        elif result.get('cancelled'):
            self.jobs.pop(job_id, None)
            self.job_order = [item for item in self.job_order if item != job_id]
            self._show_hint('字幕重试已取消。')
        else:
            failure = result.get('failure') or {}
            job.update({
                'status': 'failed', 'stage': '字幕下载失败', 'progress': 0,
                'meta': f"{failure.get('reason') or result.get('error', '字幕获取失败')} {failure.get('suggested_action') or ''}",
                'result': result,
            })
            self._show_hint(job['meta'], error=True)
        if not self.jobs:
            self.task_card.hide(); self.empty_queue.show()
        self._render_jobs(); self._start_pending_jobs()

    def open_history_folder(self):
        entry = self._current_history_entry()
        if not entry:
            return
        directory = Path(entry.get('video_path', '')).parent
        if directory.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))
        else:
            QMessageBox.warning(self, '文件夹不存在', '视频所在文件夹可能已被移动或删除。')

    def delete_history_with_file(self):
        entry = self._current_history_entry()
        if not entry:
            return
        path = Path(entry.get('video_path', ''))
        if path.exists() and not path.is_file():
            self._show_hint('无法删除：记录对应的不是视频文件。', error=True)
            return
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            self._show_hint('无法删除视频文件，下载记录已保留。', error=True)
            return
        try:
            _remove_history_entry(entry['id'])
        except OSError:
            self._show_hint('视频文件已删除，但无法清理下载记录。', error=True)
            return
        self._load_history()
        # 删除成功后不占用下载队列上方的提示区域。
        self.hint.clear()
        self.hint.hide()

    def open_file(self, item):
        entry = item.data(Qt.ItemDataRole.UserRole)
        path = Path(entry.get('video_path', '')) if isinstance(entry, dict) else Path(entry)
        if path.is_file(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else: QMessageBox.warning(self, '文件不存在', '该文件可能已被移动或删除。')


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet('''#root{background:#0b0d12;color:#f6f8fc;font-family:"Microsoft YaHei";}#inputCard,#taskCard{background:#151a25;border:1px solid #30394b;border-radius:18px;}#linkIcon{font-size:30px;color:#9eb8ff;}#urlInput{background:transparent;border:0;color:#f6f8fc;font-size:16px;padding:8px 0;}#urlInput:focus{outline:none;}#downloadButton{background:#4d7cff;color:white;border:0;border-radius:12px;padding:0 22px;min-height:48px;font-size:16px;font-weight:700;}#downloadButton:hover{background:#638bff;}#destinationLabel{color:#98a2b6;font-size:13px;}#destinationPath{color:#c4cfeb;font-size:13px;}#folderButton,#queueButton,#jobButton{background:#1c2331;border:1px solid #34415b;color:#e6ebf7;border-radius:9px;padding:8px 12px;min-height:34px;font-size:13px;}#folderButton:hover,#queueButton:hover,#jobButton:hover{border-color:#7194ff;background:#263452;}#queueButton:disabled{color:#626c82;background:#1a1e29;border-color:#2c3445;}#removeJobButton{background:#3b202a;border:1px solid #704052;color:#ffd8df;border-radius:9px;padding:8px 12px;min-height:34px;font-size:13px;}#removeJobButton:hover{background:#562a39;border-color:#bb5b73;}#hint,#jobMeta{color:#98a2b6;font-size:13px;}#error{color:#ff8795;font-size:13px;}#sectionTitle{font-size:17px;font-weight:700;color:#f6f8fc;}#queueSummary{font-size:13px;color:#9eb8ff;}#taskScroll,#taskViewport,#taskList{background:#151a25;border:0;}#jobRow{background:#111722;border:1px solid #283244;border-radius:12px;}#jobTitle{font-size:15px;font-weight:600;color:#f6f8fc;}#jobStage{font-size:13px;color:#9eb8ff;}QProgressBar{height:7px;border:0;border-radius:4px;background:#252d3c;}QProgressBar::chunk{background:#4d7cff;border-radius:4px;}#history{background:#151a25;border:1px solid #30394b;border-radius:16px;padding:6px;color:#f6f8fc;outline:none;}#history::item{padding:14px 12px;border-bottom:1px solid #283142;border-radius:8px;}#history::item:selected{background:#22345e;}QMenu{background:#1c2331;color:#f6f8fc;border:1px solid #3b4863;border-radius:8px;padding:6px;}QMenu::item{padding:9px 28px 9px 12px;border-radius:5px;}QMenu::item:selected{background:#2c467d;}QMenu::separator{height:1px;background:#34415b;margin:5px 8px;}''')
    app.setStyleSheet(app.styleSheet() + '''
        #root { background: #eef2f7; color: #243147; }
        #inputCard, #taskCard { background: #ffffff; border-color: #d7e0ee; }
        #linkIcon { color: #6685e8; }
        #urlInput { color: #243147; selection-background-color: #cfdcff; }
        #urlInput::placeholder { color: #8492a8; }
        #downloadButton { background: #6685e8; color: #ffffff; }
        #downloadButton:hover { background: #5273d8; }
        #destinationLabel { color: #62718a; }
        #destinationPath { color: #31415c; }
        #folderButton, #queueButton, #jobButton {
            background: #f1f5fb; border-color: #ced9ea; color: #31415c;
        }
        #folderButton:hover, #queueButton:hover, #jobButton:hover {
            background: #e6edff; border-color: #9fb5f3;
        }
        #queueButton:disabled { background: #f4f6fa; border-color: #e1e7f0; color: #98a4b5; }
        #removeJobButton { background: #fff1f3; border-color: #efbcc6; color: #a6364b; }
        #removeJobButton:hover { background: #ffe2e7; border-color: #df8c9d; }
        #hint, #jobMeta { color: #68778e; }
        #error { color: #b33b52; }
        #sectionPanel { background: #ffffff; border: 1px solid #dbe4f0; border-radius: 16px; }
        #emptyState { color: #91a0b6; font-size: 13px; line-height: 1.6; background: #f8faff; border: 1px dashed #d4deec; border-radius: 11px; }
        #sectionTitle, #jobTitle { color: #1f2d43; }
        #queueSummary, #jobStage { color: #5873c8; }
        #taskScroll, #taskViewport, #taskList { background: #ffffff; }
        #jobRow { background: #f8faff; border-color: #dbe4f2; }
        QProgressBar { background: #e4ebf5; }
        QProgressBar::chunk { background: #7692ed; }
        #history { background: #f8faff; border-color: #e1e8f2; color: #243147; padding: 4px; }
        #history::item { border-bottom-color: #e5ebf3; padding: 13px 12px; border-radius: 9px; }
        #history::item:hover { background: #f0f4ff; }
        #history::item:selected { background: #e4ebff; color: #243147; }
        QMenu { background: #ffffff; color: #243147; border-color: #d0dbea; }
        QMenu::item:selected { background: #e6edff; }
        QMenu::separator { background: #e1e7f0; }
        #authorizationButton, #manualAuthorizationButton { background: #eef4ff; border: 1px solid #b9caef; color: #415d9f; border-radius: 9px; padding: 8px 12px; min-height: 34px; font-size: 13px; }
        #authorizationButton:hover, #manualAuthorizationButton:hover { background: #e0ebff; border-color: #8da9e5; }
        #reauthorizeButton { background: #5478e8; border: 1px solid #5478e8; color: #ffffff; border-radius: 9px; padding: 8px 16px; min-height: 36px; font-size: 14px; font-weight: 600; }
        #reauthorizeButton:hover { background: #466ad6; }
        #reauthorizeButton:disabled, #authorizationButton:disabled { background: #edf1f8; border-color: #d7dfeb; color: #9aa8bb; }
        #authorizationTitle { color: #243147; font-size: 18px; font-weight: 700; }
        #authorizationHelp, #authorizationState { color: #68778e; font-size: 13px; }
        #authorizationError { color: #b84b5d; font-size: 13px; }
        #authorizationInput { min-height: 34px; border: 1px solid #bfcde1; border-radius: 8px; padding: 0 10px; color: #243147; background: #ffffff; }
        #authorizationInput:focus { border: 2px solid #6685e8; }
        QPlainTextEdit, QLineEdit { selection-background-color: #cfdcff; }
        #destinationLabel { font-weight: 600; }
        #destinationPath { background: #e8eef8; border-radius: 7px; padding: 7px 10px; }
        #hint { background: #edf3ff; border: 1px solid #d6e2fb; border-radius: 8px; padding: 8px 10px; }
    ''')
    window = MainWindow(); window.show(); sys.exit(app.exec())


if __name__ == '__main__': main()
