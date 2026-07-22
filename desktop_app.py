"""Native Windows desktop video downloader."""

import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QProgressBar, QMenu,
    QVBoxLayout, QWidget, QFileDialog, QScrollArea, QPlainTextEdit, QSizePolicy,
    QDialog, QDialogButtonBox, QLineEdit,
)

from lib.downloader import download_video

ROOT = Path(__file__).resolve().parent
APP_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'VideoLinkAnalyzer'
HISTORY_FILE = APP_DIR / 'history.json'
SETTINGS_FILE = APP_DIR / 'settings.json'
DOWNLOAD_DIR = Path.home() / 'Videos' / 'Video Link Analyzer'


def _history() -> list[dict]:
    try:
        return json.loads(HISTORY_FILE.read_text(encoding='utf-8'))[:20]
    except (OSError, json.JSONDecodeError):
        return []


def _save_history(item: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps([item, *_history()][:20], ensure_ascii=False, indent=2), encoding='utf-8')


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


def _saved_download_dir() -> Path:
    value = _settings().get('download_dir')
    return Path(value) if value else DOWNLOAD_DIR


def _save_download_dir(directory: Path) -> None:
    settings = _settings()
    settings['download_dir'] = str(directory)
    _save_settings(settings)


def _human_size(value: int | None) -> str:
    if not value:
        return ''
    if value >= 1024 ** 3:
        return f'{value / 1024 ** 3:.2f} GB'
    return f'{value / 1024 ** 2:.1f} MB'


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
        self.events = DownloadEvents()
        self.events.progress.connect(self._update_progress)
        self.events.finished.connect(self._finished)
        self.jobs: dict[str, dict] = {}
        self.job_order: list[str] = []
        self.pending_job_ids: list[str] = []
        self.active_job_ids: set[str] = set()
        self.authorization_session = None
        self.paused = False
        self.max_parallel_downloads = 2
        self.output_dir = _saved_download_dir()
        self.setWindowTitle('视频下载')
        self.setMinimumSize(980, 680)
        self.resize(1180, 760)
        icon = ROOT / 'assets' / 'video-download-round.ico'
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self._build()
        self._render_jobs()
        self._load_history()

    def _build(self):
        root = QWidget(); root.setObjectName('root'); self.setCentralWidget(root)
        layout = QVBoxLayout(root); layout.setContentsMargins(48, 42, 48, 36); layout.setSpacing(26)
        card = QFrame(); card.setObjectName('inputCard'); card_layout = QHBoxLayout(card); card_layout.setContentsMargins(20, 18, 16, 18); card_layout.setSpacing(14)
        link = QLabel('⌁'); link.setObjectName('linkIcon'); card_layout.addWidget(link)
        self.url = QPlainTextEdit(); self.url.setObjectName('urlInput'); self.url.setPlaceholderText('粘贴视频链接；多个链接请每行一个'); self.url.setFixedHeight(76); card_layout.addWidget(self.url, 1)
        self.button = QPushButton('加入下载队列'); self.button.clicked.connect(self.start_download); self.button.setObjectName('downloadButton'); card_layout.addWidget(self.button)
        layout.addWidget(card)
        destination = QHBoxLayout(); destination.setSpacing(10)
        label = QLabel('保存位置'); label.setObjectName('destinationLabel'); destination.addWidget(label)
        self.destination_path = QLabel(); self.destination_path.setObjectName('destinationPath'); destination.addWidget(self.destination_path, 1)
        self.folder_button = QPushButton('选择文件夹'); self.folder_button.setObjectName('folderButton'); self.folder_button.clicked.connect(self.choose_folder); destination.addWidget(self.folder_button)
        self.authorization_button = QPushButton('视频号授权'); self.authorization_button.setObjectName('authorizationButton'); self.authorization_button.clicked.connect(self.show_wechat_authorization); destination.addWidget(self.authorization_button)
        layout.addLayout(destination)
        self._refresh_destination()
        self.hint = QLabel(); self.hint.setObjectName('hint'); self.hint.hide(); layout.addWidget(self.hint)
        columns = QHBoxLayout(); columns.setContentsMargins(0, 0, 0, 0); columns.setSpacing(32)
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
        right = QVBoxLayout(); history_title = QLabel('最近下载'); history_title.setObjectName('sectionTitle'); right.addWidget(history_title)
        self.history = QListWidget(); self.history.setMinimumHeight(190); self.history.setObjectName('history'); self.history.itemDoubleClicked.connect(self.open_file); self.history.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.history.customContextMenuRequested.connect(self.show_history_menu); right.addWidget(self.history)
        columns.addLayout(left, 3); columns.addLayout(right, 2)
        columns.setAlignment(left, Qt.AlignmentFlag.AlignTop)
        columns.setAlignment(right, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(columns); layout.addStretch(1)

    def _refresh_destination(self):
        self.destination_path.setText(str(self.output_dir))
        self.destination_path.setToolTip(str(self.output_dir))

    def _show_hint(self, message: str, *, error: bool = False) -> None:
        self.hint.setText(message)
        self.hint.setObjectName('error' if error else 'hint')
        self.hint.show()
        self.hint.style().unpolish(self.hint)
        self.hint.style().polish(self.hint)

    def choose_folder(self):
        selected = QFileDialog.getExistingDirectory(self, '选择视频保存文件夹', str(self.output_dir))
        if selected:
            self.output_dir = Path(selected)
            self._refresh_destination()
            try:
                _save_download_dir(self.output_dir)
            except OSError:
                self._show_hint('已选择新位置，但系统无法记住它；本次下载仍会使用该位置。', error=True)
            else:
                self._show_hint('已保存新的下载位置，之后的下载都会使用这里。')

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
        host_match = re.match(r'https?://([^/]+)', url, flags=re.IGNORECASE)
        host = host_match.group(1).lower() if host_match else ''
        return host == 'kuaishou.com' or host.endswith('.kuaishou.com') or host.endswith('.gifshow.com')

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
        existing_urls = {job['url'] for job in self.jobs.values()}
        added = 0
        for url in urls:
            if url in existing_urls:
                continue
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {'id': job_id, 'url': url, 'title': url, 'stage': '等待下载', 'status': 'waiting', 'progress': 0, 'output_dir': str(self.output_dir)}
            self.job_order.append(job_id); self.pending_job_ids.append(job_id); existing_urls.add(url); added += 1
        self.url.clear(); self.task_card.show(); self.hint.hide()
        self._start_pending_jobs()
        if added:
            self._show_hint(f'已加入 {added} 个链接，默认同时下载 {self.max_parallel_downloads} 个。')
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
        def report(data): self.events.progress.emit(job_id, data)
        try:
            output_dir = Path(job['output_dir']); output_dir.mkdir(parents=True, exist_ok=True)
            result = download_video(job['url'], str(output_dir), progress_callback=report)
        except Exception as exc:
            result = {'success': False, 'error': f'无法保存或下载视频：{exc}'}
        self.events.finished.emit(job_id, result)

    def _update_progress(self, job_id: str, data: dict):
        job = self.jobs.get(job_id)
        if not job:
            return
        job['stage'] = data.get('stage', '正在下载')
        if 'progress' in data:
            job['progress'] = int(data['progress']) if data['progress'] is not None else None
        self._render_jobs()

    def _finished(self, job_id: str, result: dict):
        job = self.jobs.get(job_id); self.active_job_ids.discard(job_id)
        if not job:
            self._start_pending_jobs(); return
        if not result.get('success'):
            job.update({'status': 'failed', 'stage': '下载失败', 'progress': 0})
            self._show_hint(result.get('error', '无法下载该链接'), error=True)
            self._render_jobs(); self._start_pending_jobs(); return
        metadata = result.get('metadata', {}); title = metadata.get('title') or Path(result['video_path']).stem
        compatibility = result.get('compatibility') or {}; compatibility_status = compatibility.get('status')
        if compatibility_status and compatibility_status not in {'converted', 'already_compatible'}:
            self._show_hint('视频已保存，但兼容性检查没有完成；请确认已安装 ffmpeg。', error=True)
        else:
            job.update({'stage': '下载完成', 'meta': f"已保存 · {_human_size(result.get('size'))}"})
        try:
            _save_history({'id': uuid.uuid4().hex, 'title': title, 'video_path': result['video_path'], 'size': result.get('size', 0), 'created_at': int(time.time())})
            self._load_history()
        except OSError:
            self._show_hint('视频已下载，但系统无法保存下载记录。', error=True)
        # 成功下载后的文件已出现在“最近下载”中，不再占用下载队列。
        self.job_order = [item for item in self.job_order if item != job_id]
        self.pending_job_ids = [item for item in self.pending_job_ids if item != job_id]
        self.jobs.pop(job_id, None)
        if not self.jobs:
            self.task_card.hide()
        self._render_jobs(); self._start_pending_jobs()

    def _render_jobs(self):
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

    def _job_row(self, job: dict) -> QFrame:
        row = QFrame(); row.setObjectName('jobRow')
        content = QVBoxLayout(row); content.setContentsMargins(16, 14, 16, 14); content.setSpacing(10)
        title = QLabel(job.get('title', job['url'])); title.setObjectName('jobTitle'); title.setWordWrap(True)
        title.setToolTip(job.get('title', job['url']))
        content.addWidget(title)
        progress = QProgressBar(); progress.setRange(0, 100)
        progress.setValue(int(job.get('progress') or 0))
        is_downloading = job.get('stage') in {'正在下载', '正在下载视频'}
        progress.setTextVisible(is_downloading and job.get('progress') is not None)
        if progress.isTextVisible():
            progress.setFormat('下载中 %p%')
        content.addWidget(progress)
        return row

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
            item = QListWidgetItem(f"{entry['title']}\n{_human_size(entry.get('size'))}   ·   双击打开")
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
        menu.addSeparator()
        delete_file = menu.addAction('删除记录和视频文件')
        selected = menu.exec(self.history.viewport().mapToGlobal(point))
        if selected == open_folder:
            self.open_history_folder()
        elif selected == delete_file:
            self.delete_history_with_file()

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
        #root { background: #f4f7fb; color: #243147; }
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
        #sectionTitle, #jobTitle { color: #243147; }
        #queueSummary, #jobStage { color: #5873c8; }
        #taskScroll, #taskViewport, #taskList { background: #ffffff; }
        #jobRow { background: #f8faff; border-color: #dbe4f2; }
        QProgressBar { background: #e4ebf5; }
        QProgressBar::chunk { background: #7692ed; }
        #history { background: #ffffff; border-color: #d7e0ee; color: #243147; }
        #history::item { border-bottom-color: #e5ebf3; }
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
    ''')
    window = MainWindow(); window.show(); sys.exit(app.exec())


if __name__ == '__main__': main()