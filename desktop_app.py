"""Native Windows desktop application for Video Link Analyzer."""

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QProgressBar,
    QVBoxLayout, QWidget, QFileDialog,
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


def _saved_download_dir() -> Path:
    try:
        value = json.loads(SETTINGS_FILE.read_text(encoding='utf-8')).get('download_dir')
        if value:
            return Path(value)
    except (OSError, json.JSONDecodeError):
        pass
    return DOWNLOAD_DIR


def _save_download_dir(directory: Path) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps({'download_dir': str(directory)}, ensure_ascii=False), encoding='utf-8')


def _human_size(value: int | None) -> str:
    if not value:
        return ''
    if value >= 1024 ** 3:
        return f'{value / 1024 ** 3:.2f} GB'
    return f'{value / 1024 ** 2:.1f} MB'


class DownloadEvents(QObject):
    progress = Signal(dict)
    finished = Signal(dict)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.events = DownloadEvents()
        self.events.progress.connect(self._update_progress)
        self.events.finished.connect(self._finished)
        self.active_job: dict | None = None
        self.output_dir = _saved_download_dir()
        self.setWindowTitle('Video Link Analyzer')
        self.setMinimumSize(980, 680)
        self.resize(1180, 760)
        icon = ROOT / 'assets' / 'app-icon.ico'
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self._build()
        self._load_history()

    def _build(self):
        root = QWidget(); root.setObjectName('root'); self.setCentralWidget(root)
        layout = QVBoxLayout(root); layout.setContentsMargins(48, 34, 48, 36); layout.setSpacing(26)
        top = QHBoxLayout(); brand = QLabel('▷  Video Link Analyzer'); brand.setObjectName('brand')
        status = QLabel('●  桌面下载器已就绪'); status.setObjectName('status')
        top.addWidget(brand); top.addStretch(); top.addWidget(status); layout.addLayout(top)
        eyebrow = QLabel('LOCAL VIDEO TOOL'); eyebrow.setObjectName('eyebrow'); layout.addWidget(eyebrow)
        title = QLabel('把链接交给我，\n剩下的交给下载器。'); title.setObjectName('title'); layout.addWidget(title)
        card = QFrame(); card.setObjectName('inputCard'); card_layout = QHBoxLayout(card); card_layout.setContentsMargins(20, 18, 16, 18); card_layout.setSpacing(14)
        link = QLabel('⌁'); link.setObjectName('linkIcon'); card_layout.addWidget(link)
        self.url = QLineEdit(); self.url.setPlaceholderText('粘贴 B 站、抖音或视频号链接'); self.url.setClearButtonEnabled(True); self.url.returnPressed.connect(self.start_download); card_layout.addWidget(self.url, 1)
        self.button = QPushButton('开始下载  ↗'); self.button.clicked.connect(self.start_download); self.button.setObjectName('downloadButton'); card_layout.addWidget(self.button)
        layout.addWidget(card)
        destination = QHBoxLayout(); destination.setSpacing(10)
        label = QLabel('保存位置'); label.setObjectName('destinationLabel'); destination.addWidget(label)
        self.destination_path = QLabel(); self.destination_path.setObjectName('destinationPath'); destination.addWidget(self.destination_path, 1)
        self.folder_button = QPushButton('选择文件夹'); self.folder_button.setObjectName('folderButton'); self.folder_button.clicked.connect(self.choose_folder); destination.addWidget(self.folder_button)
        layout.addLayout(destination)
        self._refresh_destination()
        self.hint = QLabel(); self.hint.setObjectName('hint'); self.hint.hide(); layout.addWidget(self.hint)
        columns = QHBoxLayout(); columns.setSpacing(32)
        left = QVBoxLayout(); header = QLabel('当前任务'); header.setObjectName('sectionTitle'); left.addWidget(header)
        self.task_card = QFrame(); self.task_card.setObjectName('taskCard'); task = QVBoxLayout(self.task_card); task.setContentsMargins(22, 18, 22, 18); task.setSpacing(10)
        self.task_title = QLabel('粘贴一个链接，下载状态会显示在这里。'); self.task_title.setObjectName('taskTitle'); self.task_title.setWordWrap(True); task.addWidget(self.task_title)
        self.task_stage = QLabel('等待下载'); self.task_stage.setObjectName('taskStage'); task.addWidget(self.task_stage)
        self.progress = QProgressBar(); self.progress.setRange(0, 0); self.progress.setTextVisible(False); task.addWidget(self.progress)
        self.task_meta = QLabel(''); self.task_meta.setObjectName('hint'); task.addWidget(self.task_meta); left.addWidget(self.task_card); left.addStretch()
        self.task_card.hide()
        right = QVBoxLayout(); history_title = QLabel('最近下载'); history_title.setObjectName('sectionTitle'); right.addWidget(history_title)
        self.history = QListWidget(); self.history.setObjectName('history'); self.history.itemDoubleClicked.connect(self.open_file); right.addWidget(self.history, 1)
        columns.addLayout(left, 3); columns.addLayout(right, 2); layout.addLayout(columns, 1)

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

    def start_download(self):
        url = self.url.text().strip()
        if not url.startswith(('http://', 'https://')):
            self._show_hint('请输入完整的视频链接。', error=True); return
        if self.active_job:
            self._show_hint('已有下载任务正在进行，请稍候。'); return
        self.active_job = {'id': uuid.uuid4().hex, 'url': url, 'stage': '正在解析链接'}
        self.button.setEnabled(False); self.url.setEnabled(False); self.folder_button.setEnabled(False); self.progress.setRange(0, 0)
        self.hint.hide()
        self.task_card.show()
        self.task_title.setText('正在识别视频信息…'); self.task_stage.setText('正在解析链接'); self.task_meta.setText('请保持程序打开。')
        threading.Thread(target=self._download_worker, daemon=True).start()

    def _download_worker(self):
        def report(data): self.events.progress.emit(data)
        job = self.active_job or {}
        output_dir = self.output_dir
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            result = download_video(job['url'], str(output_dir), progress_callback=report)
        except Exception as exc:
            result = {'success': False, 'error': f'无法保存或下载视频：{exc}'}
        self.events.finished.emit(result)

    def _update_progress(self, data):
        self.task_stage.setText(data.get('stage', '正在下载'))
        progress = data.get('progress')
        if progress is not None:
            self.progress.setRange(0, 100); self.progress.setValue(int(progress))
        details = [_human_size(data.get('downloaded_bytes')), _human_size(data.get('total_bytes'))]
        if data.get('speed'): details.append(f"{data['speed'] / 1024 / 1024:.1f} MB/s")
        self.task_meta.setText(' · '.join(item for item in details if item))

    def _finished(self, result):
        self.button.setEnabled(True); self.url.setEnabled(True); self.folder_button.setEnabled(True); self.active_job = None
        if not result.get('success'):
            self.task_stage.setText('下载失败'); self.task_meta.setText(result.get('error', '无法下载该链接')); self.progress.setRange(0, 100); self.progress.setValue(0); return
        metadata = result.get('metadata', {}); title = metadata.get('title') or Path(result['video_path']).stem
        self.task_title.setText(title); self.task_stage.setText('下载完成'); self.task_meta.setText(f"已保存 · {_human_size(result.get('size'))}"); self.progress.setRange(0, 100); self.progress.setValue(100)
        try:
            _save_history({'id': uuid.uuid4().hex, 'title': title, 'video_path': result['video_path'], 'size': result.get('size', 0), 'created_at': int(time.time())})
            self._load_history()
        except OSError:
            self._show_hint('视频已下载，但系统无法保存下载记录。', error=True)

    def _load_history(self):
        self.history.clear()
        for entry in _history():
            item = QListWidgetItem(f"{entry['title']}\n{_human_size(entry.get('size'))}   ·   双击打开")
            item.setData(Qt.ItemDataRole.UserRole, entry.get('video_path')); self.history.addItem(item)

    def open_file(self, item):
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        if path.is_file(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else: QMessageBox.warning(self, '文件不存在', '该文件可能已被移动或删除。')


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet('''#root{background:#0b0d12;color:#f6f8fc;font-family:"Microsoft YaHei";}#brand{font-size:20px;font-weight:700;color:#f6f8fc;}#status{color:#92a7d5;font-size:13px;}#eyebrow{color:#83a3ff;font-size:12px;font-weight:700;letter-spacing:2px;}#title{font-size:44px;font-weight:700;line-height:1.08;color:#f6f8fc;}#inputCard,#taskCard{background:#151a25;border:1px solid #30394b;border-radius:18px;}#linkIcon{font-size:30px;color:#9eb8ff;}QLineEdit{background:transparent;border:0;color:#f6f8fc;font-size:17px;min-height:46px;}QLineEdit:focus{outline:none;}#downloadButton{background:#4d7cff;color:white;border:0;border-radius:12px;padding:0 22px;min-height:48px;font-size:16px;font-weight:700;}#downloadButton:hover{background:#638bff;}#downloadButton:disabled{background:#2f3e70;color:#b5c0e0;}#destinationLabel{color:#98a2b6;font-size:13px;}#destinationPath{color:#c4cfeb;font-size:13px;}#folderButton{background:#1c2331;border:1px solid #34415b;color:#e6ebf7;border-radius:9px;padding:8px 12px;font-size:13px;}#folderButton:hover{border-color:#7194ff;background:#263452;}#hint{color:#98a2b6;font-size:13px;}#error{color:#ff8795;font-size:13px;}#sectionTitle{font-size:17px;font-weight:700;color:#f6f8fc;}#taskTitle{font-size:16px;font-weight:600;color:#f6f8fc;}#taskStage{font-size:14px;color:#9eb8ff;}QProgressBar{height:7px;border:0;border-radius:4px;background:#252d3c;}QProgressBar::chunk{background:#4d7cff;border-radius:4px;}#history{background:#151a25;border:1px solid #30394b;border-radius:16px;padding:6px;color:#f6f8fc;outline:none;}#history::item{padding:14px 12px;border-bottom:1px solid #283142;border-radius:8px;}#history::item:selected{background:#22345e;}''')
    window = MainWindow(); window.show(); sys.exit(app.exec())


if __name__ == '__main__': main()
