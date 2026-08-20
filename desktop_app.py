"""Native Windows desktop video downloader."""

import json
import math
import os
import re
import shutil
import sys
import threading
import time
import uuid
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QProgressBar, QMenu,
    QVBoxLayout, QWidget, QFileDialog, QScrollArea, QPlainTextEdit, QSizePolicy,
    QDialog, QDialogButtonBox, QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox,
    QFormLayout,
)

from lib.downloader import _is_kuaishou, download_video
from lib.local_credentials import clear_ai_api_key, get_ai_api_key, save_ai_api_key

ROOT = Path(__file__).resolve().parent
APP_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'VideoLinkAnalyzer'
HISTORY_FILE = APP_DIR / 'history.json'
SETTINGS_FILE = APP_DIR / 'settings.json'
# Keep the repository portable: a machine-specific Vault is stored in settings.
DEFAULT_OBSIDIAN_VAULT = Path.home() / 'Videos' / 'VideoLinkAnalyzerVault'
OBSIDIAN_VAULT = DEFAULT_OBSIDIAN_VAULT
OBSIDIAN_VIDEO_DIR = OBSIDIAN_VAULT / '视频库'
OBSIDIAN_RECORD_DIR = OBSIDIAN_VIDEO_DIR / '记录'
INDEX_DB = OBSIDIAN_VIDEO_DIR / '视频索引.sqlite3'
MEMORY_FILE = OBSIDIAN_VIDEO_DIR / 'AI对话记忆.md'

AI_PRESETS = {
    'Agnes AI': {
        'base_url': 'https://apihub.agnes-ai.com/v1/chat/completions',
        'model': 'agnes-2.5-flash',
    },
    'OpenAI': {
        'base_url': 'https://api.openai.com/v1/chat/completions',
        'model': 'gpt-4o-mini',
    },
    'DeepSeek': {
        'base_url': 'https://api.deepseek.com/v1/chat/completions',
        'model': 'deepseek-chat',
    },
    'OpenRouter': {
        'base_url': 'https://openrouter.ai/api/v1/chat/completions',
        'model': 'openai/gpt-4o-mini',
    },
    'Ollama（本地）': {
        'base_url': 'http://127.0.0.1:11434/v1/chat/completions',
        'model': 'qwen2.5:7b',
    },
    '自定义 OpenAI 兼容': {'base_url': '', 'model': ''},
}

CONTENT_CATEGORIES = {
    '教程': ('教程', '教学', '课程', '入门', 'how to', 'tutorial', '实操', '方法'),
    '设计': ('设计', 'ui', 'ux', '视觉', '交互', '平面', '字体', '品牌', 'figma'),
    '编程': ('编程', '代码', 'python', 'javascript', '程序', '开发', 'api', '软件', '前端', '后端'),
    '产品': ('产品', '产品经理', '需求', '用户体验', '增长', 'app', '功能分析'),
    '营销': ('营销', '广告', '运营', '品牌营销', '投放', '社媒', '内容营销'),
    '旅行': ('旅行', '旅游', '攻略', '景点', '酒店', '美食', 'vlog'),
    '影视': ('电影', '电视剧', '纪录片', '剪辑', '综艺', '音乐', 'mv'),
}


def _ai_config() -> dict:
    """Read the current OpenAI-compatible provider configuration."""
    configured = _settings().get('ai') or {}
    try:
        temperature = float(configured.get('temperature', 0.2))
    except (TypeError, ValueError):
        temperature = 0.2
    try:
        timeout = int(configured.get('timeout', 45))
    except (TypeError, ValueError):
        timeout = 45
    return {
        'provider': configured.get('provider') or os.environ.get('AGNES_PROVIDER', 'Agnes AI'),
        'base_url': configured.get('base_url') or os.environ.get(
            'AGNES_API_BASE_URL', 'https://apihub.agnes-ai.com/v1/chat/completions'
        ),
        'api_key': get_ai_api_key() or configured.get('api_key') or os.environ.get('AGNES_API_KEY', ''),
        'model': configured.get('model') or os.environ.get('AGNES_MODEL', 'agnes-2.5-flash'),
        'temperature': max(0.0, min(2.0, temperature)),
        'timeout': max(5, min(180, timeout)),
    }


def _ai_is_configured(config: dict) -> bool:
    endpoint = str(config.get('base_url') or '').strip()
    model = str(config.get('model') or '').strip()
    local_endpoint = endpoint.startswith(('http://127.0.0.1', 'http://localhost', 'http://[::1]'))
    return bool(endpoint and model and (config.get('api_key') or local_endpoint))


def _ai_chat(messages: list[dict], config: dict | None = None, *, temperature: float | None = None) -> str:
    """Call any OpenAI-compatible chat-completions endpoint."""
    config = config or _ai_config()
    if not _ai_is_configured(config):
        raise ValueError('尚未完成 AI API 配置。')
    body = json.dumps({
        'model': config['model'],
        'temperature': config['temperature'] if temperature is None else temperature,
        'messages': messages,
    }, ensure_ascii=False).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if config.get('api_key'):
        headers['Authorization'] = f"Bearer {config['api_key']}"
    request = urllib.request.Request(config['base_url'], data=body, headers=headers, method='POST')
    with urllib.request.urlopen(request, timeout=config['timeout']) as response:
        payload = json.loads(response.read().decode('utf-8'))
    return str(payload['choices'][0]['message']['content']).strip()


def _test_ai_connection(config: dict) -> tuple[bool, str]:
    try:
        answer = _ai_chat([
            {'role': 'system', 'content': '你是连接测试助手，只回复“连接成功”。'},
            {'role': 'user', 'content': '请测试连接。'},
        ], config, temperature=0)
        return True, f'连接成功：{answer[:60]}'
    except Exception as exc:
        return False, f'连接失败：{exc}'


def _classify_content(result: dict, title: str) -> str:
    if result.get('ai_category'):
        return str(result['ai_category'])
    metadata = result.get('metadata') or {}
    text = ' '.join(str(metadata.get(key) or '') for key in ('title', 'description', 'channel', 'uploader'))
    text += ' ' + str(result.get('subtitle_text') or '')[:12000]
    text = text.lower()
    scores = {
        category: sum(text.count(keyword.lower()) for keyword in keywords)
        for category, keywords in CONTENT_CATEGORIES.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else '其他'


def _ai_classify_content(result: dict, title: str) -> dict:
    """Ask the configured OpenAI-compatible endpoint for semantic metadata."""
    config = _ai_config()
    if not _ai_is_configured(config):
        return {}
    metadata = result.get('metadata') or {}
    context = (
        f"标题：{title}\n"
        f"简介：{metadata.get('description', '')}\n"
        f"频道：{metadata.get('channel', '') or metadata.get('uploader', '')}\n"
        f"字幕：{(result.get('subtitle_text') or '')[:12000]}"
    )
    prompt = (
        '请分析这段视频资料并返回严格 JSON，不要 Markdown。'
        'category 只能是：教程、设计、编程、产品、营销、旅行、影视、其他。'
        'tags 返回 3-8 个中文关键词，summary 返回不超过120字的中文摘要。\n\n'
        + context
    )
    try:
        content = _ai_chat([
            {'role': 'system', 'content': '你是个人视频知识库整理助手。'},
            {'role': 'user', 'content': prompt},
        ], config, temperature=0.1)
        content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content).strip()
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', content, flags=re.S)
            if not match:
                return {}
            data = json.loads(match.group(0))
        category = str(data.get('category') or '其他')
        if category not in CONTENT_CATEGORIES and category != '其他':
            category = '其他'
        tags = data.get('tags') if isinstance(data.get('tags'), list) else []
        return {'ai_category': category, 'ai_tags': [str(tag) for tag in tags[:8]], 'ai_summary': str(data.get('summary') or '')}
    except (OSError, KeyError, TypeError, ValueError, urllib.error.URLError):
        return {}


def _record_frontmatter(text: str) -> dict:
    values = {}
    match = re.match(r'^---\s*\n(.*?)\n---', text, flags=re.S)
    if match:
        for line in match.group(1).splitlines():
            key, sep, value = line.partition(':')
            if sep:
                values[key.strip()] = value.strip().strip('"')
    return values


def _sync_search_index() -> None:
    INDEX_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(INDEX_DB) as db:
        db.execute('CREATE TABLE IF NOT EXISTS records (path TEXT PRIMARY KEY, mtime REAL, title TEXT, category TEXT, tags TEXT, content TEXT)')
        paths = list(OBSIDIAN_RECORD_DIR.rglob('*.md')) if OBSIDIAN_RECORD_DIR.exists() else []
        existing = {str(path) for path in paths}
        indexed = [row[0] for row in db.execute('SELECT path FROM records').fetchall()]
        for stale_path in indexed:
            if stale_path not in existing:
                db.execute('DELETE FROM records WHERE path = ?', (stale_path,))
        for path in paths:
            mtime = path.stat().st_mtime
            row = db.execute('SELECT mtime FROM records WHERE path = ?', (str(path),)).fetchone()
            if row and row[0] >= mtime:
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
            front = _record_frontmatter(text)
            db.execute('INSERT OR REPLACE INTO records(path,mtime,title,category,tags,content) VALUES(?,?,?,?,?,?)',
                       (str(path), mtime, front.get('title', path.stem), front.get('category', ''), front.get('tags', ''), text))
        db.commit()


def _search_database(question: str, limit: int = 10, fallback: bool = True) -> list[str]:
    _sync_search_index()
    terms = re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}', question.lower())
    with sqlite3.connect(INDEX_DB) as db:
        rows = db.execute('SELECT path,title,category,tags,content FROM records').fetchall()
    def grams(value: str) -> dict[str, int]:
        compact = re.sub(r'\s+', '', value.lower())
        return {compact[i:i + 2]: compact.count(compact[i:i + 2]) for i in range(max(0, len(compact) - 1))}
    query_grams = grams(question)
    scored = []
    for path, title, category, tags, content in rows:
        haystack = f'{title} {category} {tags} {content}'.lower()
        keyword_score = sum(haystack.count(term) for term in terms)
        record_grams = grams(haystack)
        overlap = sum(count * record_grams.get(token, 0) for token, count in query_grams.items())
        qnorm = math.sqrt(sum(value * value for value in query_grams.values())) or 1
        rnorm = math.sqrt(sum(value * value for value in record_grams.values())) or 1
        score = keyword_score * 10 + overlap / (qnorm * rnorm)
        scored.append((score, f'来源记录：{path}\n{content}'))
    scored.sort(key=lambda item: item[0], reverse=True)
    hits = [content for score, content in scored if score > 0][:limit]
    if hits:
        return hits
    return [content for _, content in scored[:limit]] if fallback else []


def _expand_query(question: str) -> str:
    """Use the chat model to add search terms without sending vault records."""
    config = _ai_config()
    if not _ai_is_configured(config):
        return question
    try:
        expansion = _ai_chat([
            {'role': 'system', 'content': '你是检索词生成器，只输出逗号分隔的中文关键词和同义词，不要解释。'},
            {'role': 'user', 'content': f'为视频知识库检索扩展这个问题：{question}'},
        ], config, temperature=0)
        return f'{question} {expansion[:300]}'
    except (OSError, KeyError, TypeError, ValueError, urllib.error.URLError):
        return question


def _query_ai_database(question: str, conversation: list[dict] | None = None) -> str:
    """Answer a question using the Markdown records in the active video vault."""
    config = _ai_config()
    if not _ai_is_configured(config):
        return '尚未完成 AI API 配置，请点击主界面的“AI 配置”。'
    records = _search_database(question, fallback=False)
    if not records:
        expanded_question = _expand_query(question)
        records = _search_database(expanded_question)
    if not records:
        records = _search_database(question, fallback=True)
    context = '\n\n---\n\n'.join(record[:5000] for record in records) or '当前视频库还没有记录。'
    long_term_memory = _relevant_long_term_memory(question)
    prompt = (
        '你是本地视频知识库助手。请只根据下面的数据库记录回答用户问题；'
        '如果记录中没有答案，请明确说“数据库中没有找到相关内容”，不要编造。'
        '回答最后列出相关视频标题和来源记录路径。'
        f'\n\n数据库记录：\n{context}'
        f'\n\n长期对话记忆：\n{long_term_memory or "暂无"}'
        f'\n\n用户问题：{question}'
    )
    messages = [{'role': 'system', 'content': '你是严谨的视频知识库问答助手。'}]
    messages.extend((conversation or [])[-8:])
    messages.append({'role': 'user', 'content': prompt})
    try:
        return _ai_chat(messages, config)
    except (OSError, KeyError, TypeError, ValueError, urllib.error.URLError) as exc:
        return f'AI 查询失败：{exc}'


def _save_conversation_memory(question: str, answer: str) -> None:
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    with MEMORY_FILE.open('a', encoding='utf-8') as handle:
        handle.write(f'\n## {stamp}\n\n**用户：** {question}\n\n**AI：** {answer}\n')
    try:
        content = MEMORY_FILE.read_text(encoding='utf-8')
        if len(content) > 100000:
            sections = content.split('\n## ')
            MEMORY_FILE.write_text('\n## '.join([''] + sections[-40:]), encoding='utf-8')
    except OSError:
        pass


def _relevant_long_term_memory(question: str, limit: int = 5000) -> str:
    try:
        content = MEMORY_FILE.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''
    sections = [section for section in content.split('\n## ') if section.strip()]
    if not sections:
        return ''
    terms = re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}', question.lower())
    references_past = any(word in question for word in ('刚才', '之前', '上次', '记得', '我们说过'))
    scored = []
    for index, section in enumerate(sections):
        lower = section.lower()
        score = sum(lower.count(term) for term in terms) + (index / max(1, len(sections)) if references_past else 0)
        scored.append((score, index, section))
    matches = [item for item in sorted(scored, reverse=True) if item[0] > 0]
    if not matches:
        matches = sorted(scored, key=lambda item: item[1], reverse=True)[:1] if references_past else []
    selected = []
    total = 0
    for _, _, section in matches[:6]:
        if total + len(section) > limit:
            break
        selected.append(section)
        total += len(section)
    return '\n\n---\n\n'.join(selected)


def _organize_video(result: dict, title: str) -> str:
    """Move a selected video and subtitle into a content category folder."""
    category = _classify_content(result, title)
    video_path = Path(result.get('video_path', ''))
    if video_path.is_file():
        target_dir = OBSIDIAN_VIDEO_DIR / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / video_path.name
        if target.resolve() != video_path.resolve():
            if target.exists():
                target = target_dir / f'{video_path.stem}-{int(time.time())}{video_path.suffix}'
            shutil.move(str(video_path), str(target))
            result['video_path'] = str(target)
        subtitle_path = result.get('subtitle_path')
        if subtitle_path and Path(subtitle_path).exists():
            subtitle = Path(subtitle_path)
            subtitle_target = target_dir / subtitle.name
            if subtitle_target.resolve() != subtitle.resolve():
                shutil.move(str(subtitle), str(subtitle_target))
            result['subtitle_path'] = str(subtitle_target)
    result['category'] = category
    return category


def _obsidian_value(value: object) -> str:
    """Encode a frontmatter value as a safe YAML double-quoted string."""
    return json.dumps(str(value or ''), ensure_ascii=False)


def _write_obsidian_record(source_url: str, result: dict, title: str) -> None:
    """Create one Obsidian record for a successfully downloaded video."""
    video_path = Path(result.get('video_path', ''))
    if not video_path.exists() or not video_path.is_relative_to(OBSIDIAN_VAULT):
        return
    OBSIDIAN_RECORD_DIR.mkdir(parents=True, exist_ok=True)
    relative_video = video_path.relative_to(OBSIDIAN_VAULT).as_posix()
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip(' .') or video_path.stem
    record_path = OBSIDIAN_RECORD_DIR / f'{safe_name}.md'
    if record_path.exists():
        record_path = OBSIDIAN_RECORD_DIR / f'{safe_name}-{int(time.time())}.md'
    metadata = result.get('metadata') or {}
    category = result.get('category') or '其他'
    downloaded_at = time.strftime('%Y-%m-%d %H:%M:%S')
    content = (
        '---\n'
        f'title: {_obsidian_value(title)}\n'
        f'platform: {_obsidian_value(metadata.get("platform", ""))}\n'
        f'category: {_obsidian_value(category)}\n'
        f'ai_summary: {_obsidian_value(result.get("ai_summary", ""))}\n'
        f'downloaded_at: {_obsidian_value(downloaded_at)}\n'
        'tags:\n  - video-download\n'
        f'  - {category}\n'
        + ''.join(f'  - {tag}\n' for tag in result.get('ai_tags', []))
        + '---\n\n'
        f'# {title}\n\n'
    )
    record_path.write_text(content, encoding='utf-8')


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


def _knowledge_vault() -> Path:
    configured = _settings().get('knowledge_vault') or os.environ.get('VIDEO_KNOWLEDGE_VAULT')
    return Path(configured) if configured else DEFAULT_OBSIDIAN_VAULT


def _set_knowledge_vault(vault: Path) -> None:
    """Update the active vault paths used by the indexer and record writer."""
    global OBSIDIAN_VAULT, OBSIDIAN_VIDEO_DIR, OBSIDIAN_RECORD_DIR, INDEX_DB, MEMORY_FILE
    OBSIDIAN_VAULT = Path(vault).expanduser()
    OBSIDIAN_VIDEO_DIR = OBSIDIAN_VAULT / '视频库'
    OBSIDIAN_RECORD_DIR = OBSIDIAN_VIDEO_DIR / '记录'
    INDEX_DB = OBSIDIAN_VIDEO_DIR / '视频索引.sqlite3'
    MEMORY_FILE = OBSIDIAN_VIDEO_DIR / 'AI对话记忆.md'


def _save_settings(settings: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False), encoding='utf-8')


def _migrate_plaintext_ai_key(settings: dict) -> None:
    """Move an older plaintext API key from settings.json into Windows DPAPI."""
    ai_settings = settings.get('ai')
    if not isinstance(ai_settings, dict):
        return
    plaintext_key = str(ai_settings.pop('api_key', '') or '').strip()
    if not plaintext_key:
        return
    save_ai_api_key(plaintext_key)
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


class ChatEvents(QObject):
    response = Signal(str)


class AiConfigEvents(QObject):
    result = Signal(bool, str)


class KnowledgeBaseEvents(QObject):
    finished = Signal(str, bool, str)


class ChatPanel(QFrame):
    """Frameless floating panel that can be dragged by its surface."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        settings = _settings()
        try:
            _migrate_plaintext_ai_key(settings)
        except OSError:
            pass
        configured_vault = settings.get('knowledge_vault')
        _set_knowledge_vault(_knowledge_vault())
        if not configured_vault and DEFAULT_OBSIDIAN_VAULT.exists():
            settings['knowledge_vault'] = str(DEFAULT_OBSIDIAN_VAULT)
            try:
                _save_settings(settings)
            except OSError:
                pass
        self._needs_vault_prompt = not OBSIDIAN_VAULT.exists()
        self.events = DownloadEvents()
        self.events.progress.connect(self._update_progress)
        self.events.finished.connect(self._finished)
        self.chat_events = ChatEvents()
        self.chat_events.response.connect(self._show_chat_response)
        self.knowledge_events = KnowledgeBaseEvents()
        self.knowledge_events.finished.connect(self._knowledge_base_finished)
        self._knowledge_add_ids: set[str] = set()
        self.chat_messages: list[dict] = []
        self.jobs: dict[str, dict] = {}
        self.job_order: list[str] = []
        self.pending_job_ids: list[str] = []
        self.active_job_ids: set[str] = set()
        self.cancel_events: dict[str, threading.Event] = {}
        self.authorization_session = None
        self.paused = False
        self.max_parallel_downloads = 2
        # One selected root controls both the local Vault and the download folder.
        # Videos stay in <vault>/视频库 until the user explicitly adds one to the KB.
        self.output_dir = OBSIDIAN_VIDEO_DIR
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
        label = QLabel('下载与知识库'); label.setObjectName('destinationLabel'); destination.addWidget(label)
        self.destination_path = QLabel(); self.destination_path.setObjectName('destinationPath'); self.destination_path.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed); destination.addWidget(self.destination_path, 1)
        self.folder_button = QPushButton('选择位置'); self.folder_button.setObjectName('folderButton'); self.folder_button.clicked.connect(self.choose_folder); destination.addWidget(self.folder_button)
        self.authorization_button = QPushButton('视频号授权'); self.authorization_button.setObjectName('authorizationButton'); self.authorization_button.clicked.connect(self.show_wechat_authorization); destination.addWidget(self.authorization_button)
        self.ai_config_button = QPushButton('AI 配置'); self.ai_config_button.setObjectName('aiConfigButton'); self.ai_config_button.setToolTip('配置 AI 服务商、API 地址、密钥和模型'); self.ai_config_button.clicked.connect(self.show_ai_config); destination.addWidget(self.ai_config_button)
        self.chat_toggle_button = QPushButton('AI'); self.chat_toggle_button.setObjectName('chatToggleButton'); self.chat_toggle_button.setToolTip('展开或收起 AI 知识库助手'); self.chat_toggle_button.setFixedWidth(46); self.chat_toggle_button.clicked.connect(self.toggle_chat_dock); destination.addWidget(self.chat_toggle_button)
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
        chat = ChatPanel(); chat.setObjectName('chatPanel'); chat_layout = QVBoxLayout(chat); chat_layout.setContentsMargins(14, 12, 14, 14); chat_layout.setSpacing(10)
        chat_header = QHBoxLayout(); chat_header.setContentsMargins(0, 0, 0, 0)
        chat_title = QLabel('AI 知识库助手'); chat_title.setObjectName('sectionTitle'); chat_header.addWidget(chat_title); chat_header.addStretch(1)
        chat_close = QPushButton('×'); chat_close.setObjectName('chatClose'); chat_close.setToolTip('收起 AI 助手'); chat_close.setFixedSize(28, 28); chat_close.clicked.connect(lambda: self.chat_dock.hide()); chat_header.addWidget(chat_close)
        chat_layout.addLayout(chat_header)
        self.chat_history = QPlainTextEdit(); self.chat_history.setObjectName('chatHistory'); self.chat_history.setReadOnly(True); self.chat_history.setPlaceholderText('可以问：有哪些编程教程？\n帮我找关于交互设计的视频'); chat_layout.addWidget(self.chat_history, 1)
        chat_input_row = QHBoxLayout(); chat_input_row.setSpacing(8)
        self.chat_input = QLineEdit(); self.chat_input.setObjectName('chatInput'); self.chat_input.setPlaceholderText('向视频库提问…'); self.chat_input.returnPressed.connect(self.ask_ai); chat_input_row.addWidget(self.chat_input, 1)
        self.chat_send = QPushButton('发送'); self.chat_send.setObjectName('chatSend'); self.chat_send.clicked.connect(self.ask_ai); chat_input_row.addWidget(self.chat_send)
        chat_layout.addLayout(chat_input_row)
        left_panel = QFrame(); left_panel.setObjectName('sectionPanel'); left_panel_layout = QVBoxLayout(left_panel); left_panel_layout.setContentsMargins(18, 16, 18, 18); left_panel_layout.setSpacing(12); left_panel_layout.addLayout(left)
        right_panel = QFrame(); right_panel.setObjectName('sectionPanel'); right_panel_layout = QVBoxLayout(right_panel); right_panel_layout.setContentsMargins(18, 16, 18, 18); right_panel_layout.setSpacing(12); right_panel_layout.addLayout(right)
        columns.addWidget(left_panel, 3); columns.addWidget(right_panel, 2)
        columns.setAlignment(left, Qt.AlignmentFlag.AlignTop)
        columns.setAlignment(right, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(columns); layout.addStretch(1)
        self.chat_dock = chat
        self.chat_dock.setObjectName('chatDock')
        self.chat_dock.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.chat_dock.resize(360, max(560, self.height()))
        self.chat_dock.hide()
        self._chat_initialized = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._chat_initialized:
            self._chat_initialized = True
        if self._needs_vault_prompt:
            self._needs_vault_prompt = False
            QTimer.singleShot(180, self._prompt_for_knowledge_vault)

    def _prompt_for_knowledge_vault(self):
        self._show_hint('请选择统一的下载与知识库文件夹。')
        self.choose_folder()

    def _position_chat_dock(self):
        if self.chat_dock.isVisible():
            frame = self.frameGeometry()
            self.chat_dock.setGeometry(frame.right() + 1, frame.top(), self.chat_dock.width(), frame.height())

    def toggle_chat_dock(self):
        if self.chat_dock.isVisible():
            self.chat_dock.hide()
        else:
            self.chat_dock.show()
            QTimer.singleShot(0, self._position_chat_dock)

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, 'chat_dock') and self.chat_dock.isVisible():
            self._position_chat_dock()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'chat_dock') and self.chat_dock.isVisible():
            self._position_chat_dock()

    def ask_ai(self):
        question = self.chat_input.text().strip()
        if not question:
            return
        self.chat_input.clear(); self.chat_send.setEnabled(False)
        self.chat_history.appendPlainText(f'你：{question}\nAI：正在检索视频库…')
        conversation = list(self.chat_messages[-8:])
        self.chat_messages.append({'role': 'user', 'content': question})
        threading.Thread(target=self._chat_worker, args=(question, conversation), daemon=True).start()

    def _chat_worker(self, question: str, conversation: list[dict]):
        answer = _query_ai_database(question, conversation)
        try:
            _save_conversation_memory(question, answer)
        except OSError:
            pass
        self.chat_events.response.emit(answer)

    def _show_chat_response(self, answer: str):
        self.chat_history.appendPlainText(f'{answer}\n')
        self.chat_messages.append({'role': 'assistant', 'content': answer})
        self.chat_send.setEnabled(True)

    def _refresh_destination(self):
        self.destination_path.setText(str(OBSIDIAN_VAULT))
        self.destination_path.setToolTip(f'知识库根目录：{OBSIDIAN_VAULT}\n视频下载目录：{OBSIDIAN_VIDEO_DIR}')

    def choose_knowledge_vault(self):
        """Backward-compatible alias for older callers and saved shortcuts."""
        self.choose_folder()

    def _set_unified_location(self, vault: Path) -> None:
        _set_knowledge_vault(vault)
        self.output_dir = OBSIDIAN_VIDEO_DIR
        settings = _settings()
        settings['knowledge_vault'] = str(OBSIDIAN_VAULT)
        settings['download_dir'] = str(self.output_dir)
        try:
            _save_settings(settings)
        except OSError:
            self._show_hint('位置已切换，但无法保存设置；本次运行仍会使用新位置。', error=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._refresh_destination()

    def choose_folder(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            '选择统一的下载与知识库文件夹',
            str(OBSIDIAN_VAULT if OBSIDIAN_VAULT.exists() else Path.home()),
        )
        if not directory:
            if not OBSIDIAN_VAULT.exists():
                self._show_hint('尚未选择位置；下载功能仍可使用。', error=True)
            return
        vault = Path(directory)
        if vault.name == '.obsidian':
            vault = vault.parent
        self._set_unified_location(vault)
        self._show_hint(f'已统一位置：{vault}（视频保存在“视频库”文件夹）')

    def _show_hint(self, message: str, *, error: bool = False) -> None:
        self.hint.setText(message)
        self.hint.setObjectName('error' if error else 'hint')
        self.hint.show()
        self.hint.style().unpolish(self.hint)
        self.hint.style().polish(self.hint)

    def show_ai_config(self):
        """Open the local configuration form for any OpenAI-compatible model."""
        config = _ai_config()
        dialog = QDialog(self)
        dialog.setWindowTitle('AI API 配置')
        dialog.setMinimumWidth(580)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        heading = QLabel('连接 AI 模型')
        heading.setObjectName('authorizationTitle')
        layout.addWidget(heading)
        help_text = QLabel(
            '支持 Agnes、OpenAI、DeepSeek、OpenRouter、Ollama 以及其他 OpenAI 兼容接口。\n'
            '配置只保存在本机，不会随项目上传。'
        )
        help_text.setWordWrap(True)
        help_text.setObjectName('authorizationHelp')
        layout.addWidget(help_text)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        provider = QComboBox()
        provider.setObjectName('aiProvider')
        provider.addItems(list(AI_PRESETS))
        provider_name = str(config.get('provider') or 'Agnes AI')
        provider.setCurrentText(provider_name if provider_name in AI_PRESETS else '自定义 OpenAI 兼容')
        form.addRow('服务商预设', provider)

        endpoint = QLineEdit(str(config.get('base_url') or ''))
        endpoint.setObjectName('aiEndpoint')
        endpoint.setPlaceholderText('https://api.example.com/v1/chat/completions')
        endpoint.setAccessibleName('API 地址')
        form.addRow('API 地址', endpoint)

        api_key = QLineEdit(str(config.get('api_key') or ''))
        api_key.setObjectName('aiApiKey')
        api_key.setEchoMode(QLineEdit.EchoMode.Password)
        api_key.setPlaceholderText('粘贴 API Key（Ollama 本地服务可留空）')
        api_key.setAccessibleName('API Key')
        form.addRow('API Key', api_key)

        model = QLineEdit(str(config.get('model') or ''))
        model.setObjectName('aiModel')
        model.setPlaceholderText('例如：gpt-4o-mini、deepseek-chat、qwen2.5:7b')
        model.setAccessibleName('模型名称')
        form.addRow('模型名称', model)

        temperature = QDoubleSpinBox()
        temperature.setObjectName('aiTemperature')
        temperature.setRange(0.0, 2.0)
        temperature.setSingleStep(0.1)
        temperature.setDecimals(1)
        temperature.setValue(float(config.get('temperature', 0.2)))
        temperature.setSuffix('  （越低越稳定）')
        form.addRow('创造性', temperature)

        timeout = QSpinBox()
        timeout.setObjectName('aiTimeout')
        timeout.setRange(5, 180)
        timeout.setValue(int(config.get('timeout', 45)))
        timeout.setSuffix(' 秒')
        form.addRow('请求超时', timeout)
        layout.addLayout(form)

        status = QLabel('保存后，右侧 AI 助手会立即使用新配置。')
        status.setObjectName('aiConfigStatus')
        status.setWordWrap(True)
        layout.addWidget(status)

        test_button = QPushButton('测试连接')
        test_button.setObjectName('aiTestButton')
        test_button.setAccessibleName('测试 AI 连接')
        layout.addWidget(test_button, alignment=Qt.AlignmentFlag.AlignLeft)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setText('保存配置')
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def apply_preset(name: str):
            preset = AI_PRESETS.get(name)
            if not preset or name == '自定义 OpenAI 兼容':
                return
            endpoint.setText(preset['base_url'])
            model.setText(preset['model'])

        provider.currentTextChanged.connect(apply_preset)

        def collect_config() -> dict:
            return {
                'provider': provider.currentText(),
                'base_url': endpoint.text().strip(),
                'api_key': api_key.text().strip(),
                'model': model.text().strip(),
                'temperature': round(temperature.value(), 1),
                'timeout': timeout.value(),
            }

        def set_status(message: str, *, error: bool = False):
            status.setText(message)
            status.setObjectName('authorizationError' if error else 'aiConfigStatus')
            status.style().unpolish(status)
            status.style().polish(status)

        test_events = AiConfigEvents(dialog)
        dialog._ai_test_events = test_events

        def finish_test(ok: bool, message: str):
            test_button.setEnabled(True)
            save_button.setEnabled(True)
            set_status(message, error=not ok)

        test_events.result.connect(finish_test)

        def test_connection():
            current = collect_config()
            if not current['base_url'] or not current['model']:
                set_status('请先填写 API 地址和模型名称。', error=True)
                return
            test_button.setEnabled(False)
            save_button.setEnabled(False)
            set_status('正在测试连接，请稍候…')
            threading.Thread(
                target=lambda: test_events.result.emit(*_test_ai_connection(current)),
                daemon=True,
            ).start()

        def save_config():
            current = collect_config()
            if not current['base_url'].startswith(('http://', 'https://')):
                set_status('API 地址必须以 http:// 或 https:// 开头。', error=True)
                return
            if not current['model']:
                set_status('请填写模型名称。', error=True)
                return
            api_key_value = current.pop('api_key')
            settings = _settings()
            settings['ai'] = current
            try:
                if api_key_value:
                    save_ai_api_key(api_key_value)
                else:
                    clear_ai_api_key()
                _save_settings(settings)
            except (OSError, RuntimeError) as exc:
                set_status(f'保存失败：{exc}', error=True)
                return
            if api_key_value:
                os.environ['AGNES_API_KEY'] = api_key_value
            else:
                os.environ.pop('AGNES_API_KEY', None)
            os.environ['AGNES_API_BASE_URL'] = current['base_url']
            os.environ['AGNES_MODEL'] = current['model']
            self._show_hint(f"AI 配置已保存：{current['provider']} / {current['model']}")
            dialog.accept()

        test_button.clicked.connect(test_connection)
        buttons.accepted.connect(save_config)
        dialog.exec()

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
        added = 0
        for url in urls:
            if url in existing_urls:
                continue
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {'id': job_id, 'url': url, 'title': url, 'stage': '等待下载', 'status': 'waiting', 'progress': 0, 'output_dir': str(self.output_dir)}
            self.cancel_events[job_id] = threading.Event()
            self.job_order.append(job_id); self.pending_job_ids.append(job_id); existing_urls.add(url); added += 1
        self.url.clear(); self.task_card.show(); self.empty_queue.hide(); self.hint.hide()
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
            result = download_video(
                job['url'], str(output_dir),
                progress_callback=report,
                cancel_callback=self.cancel_events[job_id].is_set,
            )
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
        self.cancel_events.pop(job_id, None)
        if not job:
            self._start_pending_jobs(); return
        if result.get('cancelled'):
            self.jobs.pop(job_id, None)
            self.job_order = [item for item in self.job_order if item != job_id]
            self.pending_job_ids = [item for item in self.pending_job_ids if item != job_id]
            self._show_hint('下载已取消。')
            self._render_jobs(); self._start_pending_jobs(); return
        if not result.get('success'):
            job.update({'status': 'failed', 'stage': '下载失败', 'progress': 0})
            self._show_hint(result.get('error', '无法下载该链接'), error=True)
            self._render_jobs(); self._start_pending_jobs(); return
        metadata = result.get('metadata', {}); title = metadata.get('title') or Path(result['video_path']).stem
        compatibility = result.get('compatibility') or {}; compatibility_status = compatibility.get('status')
        if compatibility_status in {'conversion_unavailable', 'conversion_failed'}:
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
                'metadata': result.get('metadata') or {},
                'subtitle_text': (result.get('subtitle_text') or '')[:12000],
                'subtitle_path': result.get('subtitle_path'),
                'knowledge_base': False,
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
        cancel = QPushButton('取消')
        cancel.setObjectName('removeJobButton')
        cancel.clicked.connect(lambda _checked=False, job_id=job['id']: self.cancel_job(job_id))
        content.addWidget(cancel, 0, Qt.AlignmentFlag.AlignRight)
        return row

    def cancel_job(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        event = self.cancel_events.get(job_id)
        if event:
            event.set()
        if job.get('status') == 'waiting':
            self.jobs.pop(job_id, None)
            self.cancel_events.pop(job_id, None)
            self.job_order = [item for item in self.job_order if item != job_id]
            self.pending_job_ids = [item for item in self.pending_job_ids if item != job_id]
            self._render_jobs()
            self._show_hint('等待任务已取消。')
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
            if entry.get('knowledge_base'):
                status = f"已加入知识库 · {entry.get('category', '其他')}"
            else:
                status = '右键加入知识库'
            if entry.get('id') in self._knowledge_add_ids:
                status = '正在整理到知识库…'
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
        add_to_knowledge = menu.addAction('加入知识库')
        entry = item.data(Qt.ItemDataRole.UserRole)
        already_added = isinstance(entry, dict) and entry.get('knowledge_base')
        adding = isinstance(entry, dict) and entry.get('id') in self._knowledge_add_ids
        if already_added:
            add_to_knowledge.setText('已加入知识库')
            add_to_knowledge.setEnabled(False)
        elif adding:
            add_to_knowledge.setText('正在整理…')
            add_to_knowledge.setEnabled(False)
        menu.addSeparator()
        delete_file = menu.addAction('删除记录和视频文件')
        delete_file.setEnabled(not adding)
        selected = menu.exec(self.history.viewport().mapToGlobal(point))
        if selected == open_folder:
            self.open_history_folder()
        elif selected == add_to_knowledge:
            self.add_history_to_knowledge_base()
        elif selected == delete_file:
            self.delete_history_with_file()

    def add_history_to_knowledge_base(self):
        entry = self._current_history_entry()
        if not entry or entry.get('knowledge_base') or entry.get('id') in self._knowledge_add_ids:
            return
        video_path = Path(entry.get('video_path', ''))
        if not video_path.is_file():
            self._show_hint('视频文件不存在，无法加入知识库。', error=True)
            return
        self._knowledge_add_ids.add(entry['id'])
        self._load_history()
        self._show_hint('正在分析视频内容并整理到知识库…')
        threading.Thread(target=self._add_history_worker, args=(dict(entry),), daemon=True).start()

    def _add_history_worker(self, entry: dict):
        try:
            result = {
                'success': True,
                'video_path': entry.get('video_path', ''),
                'subtitle_path': entry.get('subtitle_path'),
                'subtitle_text': entry.get('subtitle_text') or '',
                'metadata': entry.get('metadata') or {'title': entry.get('title', '')},
            }
            title = entry.get('title') or Path(result['video_path']).stem
            result.update(_ai_classify_content(result, title))
            _organize_video(result, title)
            _write_obsidian_record('', result, title)
            self.knowledge_events.finished.emit(entry['id'], True, json.dumps({
                'video_path': result.get('video_path', entry.get('video_path', '')),
                'subtitle_path': result.get('subtitle_path'),
                'category': result.get('category', '其他'),
                'ai_summary': result.get('ai_summary', ''),
                'ai_tags': result.get('ai_tags', []),
            }, ensure_ascii=False))
        except Exception as exc:
            self.knowledge_events.finished.emit(entry.get('id', ''), False, str(exc))

    def _knowledge_base_finished(self, entry_id: str, success: bool, detail: str):
        self._knowledge_add_ids.discard(entry_id)
        if not success:
            self._show_hint(f'加入知识库失败：{detail}', error=True)
            self._load_history()
            return
        try:
            metadata = json.loads(detail)
        except (TypeError, ValueError):
            metadata = {}
        entries = _history()
        for entry in entries:
            if entry.get('id') == entry_id:
                entry.update(metadata)
                entry['knowledge_base'] = True
                break
        try:
            HISTORY_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            self._show_hint('视频已整理，但无法更新最近下载状态。', error=True)
        self._load_history()
        self._show_hint('已加入知识库：完成分类、摘要和标签整理。')

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
        #chatPanel { background: #ffffff; border: 1px solid #d7e0ee; border-radius: 16px; }
        #chatHistory { background: #f8faff; border: 1px solid #e1e8f3; border-radius: 11px; padding: 12px; color: #31415c; font-size: 13px; line-height: 1.4; }
        #chatInput { min-height: 36px; background: #ffffff; border: 1px solid #cbd7e8; border-radius: 9px; padding: 0 11px; color: #243147; }
        #chatInput:focus { border: 2px solid #6685e8; }
        #chatSend { min-height: 36px; min-width: 58px; background: #6685e8; border: 0; border-radius: 9px; color: #ffffff; font-weight: 600; }
        #chatSend:hover { background: #5273d8; }
        #chatSend:disabled { background: #b7c5e7; }
        #chatToggleButton { background: #eef3ff; border: 1px solid #b9caef; color: #415d9f; border-radius: 9px; padding: 8px 13px; min-height: 34px; font-size: 13px; font-weight: 600; }
        #chatToggleButton:hover { background: #e0eaff; border-color: #8da9e5; }
        #aiConfigButton { background: #ffffff; border: 1px solid #b9caef; color: #415d9f; border-radius: 9px; padding: 8px 12px; min-height: 34px; font-size: 13px; font-weight: 600; }
        #aiConfigButton:hover { background: #e8efff; border-color: #8da9e5; }
        #aiProvider, #aiEndpoint, #aiApiKey, #aiModel, #aiTemperature, #aiTimeout { min-height: 34px; background: #ffffff; border: 1px solid #cbd7e8; border-radius: 8px; padding: 0 10px; color: #243147; }
        #aiProvider:focus, #aiEndpoint:focus, #aiApiKey:focus, #aiModel:focus, #aiTemperature:focus, #aiTimeout:focus { border: 2px solid #6685e8; }
        #aiConfigStatus { color: #68778e; font-size: 13px; background: #f7f9fd; border: 1px solid #e1e8f3; border-radius: 8px; padding: 8px 10px; }
        #aiTestButton { background: #eef4ff; border: 1px solid #b9caef; color: #415d9f; border-radius: 9px; padding: 8px 14px; min-height: 34px; font-size: 13px; }
        #aiTestButton:hover { background: #e0ebff; border-color: #8da9e5; }
        #aiTestButton:disabled { background: #edf1f8; border-color: #d7dfeb; color: #9aa8bb; }
        #chatDock { background: #eef2f7; border: 0; }
        #chatDock::title { background: #ffffff; color: #1f2d43; padding: 11px 14px; font-size: 15px; font-weight: 700; }
        #chatClose { background: transparent; border: 0; color: #8290a5; border-radius: 7px; font-size: 20px; font-weight: 500; }
        #chatClose:hover { background: #edf2fa; color: #31415c; }
        QPlainTextEdit, QLineEdit { selection-background-color: #cfdcff; }
        #destinationLabel { font-weight: 600; }
        #destinationPath { background: #e8eef8; border-radius: 7px; padding: 7px 10px; }
        #hint { background: #edf3ff; border: 1px solid #d6e2fb; border-radius: 8px; padding: 8px 10px; }
    ''')
    window = MainWindow(); window.show(); sys.exit(app.exec())


if __name__ == '__main__': main()
