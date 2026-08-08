"""Mobile-friendly local web interface for the desktop downloader.

The web server runs on the same computer as the downloader. A phone on the
same network can open the displayed address to submit downloads, inspect
recent downloads, and ask the configured AI about the local knowledge base.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from lib.downloader import download_video
import desktop_app


ROOT = Path(__file__).resolve().parent
WEB_PAGE = ROOT / 'web' / 'mobile.html'
WEB_MANIFEST = ROOT / 'web' / 'manifest.json'
WEB_SERVICE_WORKER = ROOT / 'web' / 'service-worker.js'
WEB_ICON = ROOT / 'web' / 'app-icon.svg'
MAX_BODY_BYTES = 1024 * 1024
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _refresh_vault() -> None:
    desktop_app._set_knowledge_vault(desktop_app._knowledge_vault())


def _job_view(job: dict) -> dict:
    return {
        key: job.get(key)
        for key in ('id', 'url', 'title', 'status', 'stage', 'progress', 'error')
        if job.get(key) is not None
    }


def _history_view() -> list[dict]:
    _refresh_vault()
    result = []
    for entry in desktop_app._history():
        result.append({
            'id': entry.get('id'),
            'title': entry.get('title') or '未命名视频',
            'size': entry.get('size') or 0,
            'category': entry.get('category') or '',
            'knowledge_base': bool(entry.get('knowledge_base')),
            'downloaded_at': entry.get('downloaded_at') or '',
        })
    return result


def _save_download_result(job_id: str, url: str, result: dict) -> None:
    path = Path(result.get('video_path') or '')
    metadata = result.get('metadata') or {}
    title = str(metadata.get('title') or path.stem or url)
    entry = {
        'id': job_id,
        'url': url,
        'title': title,
        'video_path': str(path),
        'size': path.stat().st_size if path.is_file() else result.get('size', 0),
        'metadata': metadata,
        'subtitle_path': result.get('subtitle_path'),
        'subtitle_text': result.get('subtitle_text'),
        'downloaded_at': __import__('time').strftime('%Y-%m-%d %H:%M:%S'),
        'knowledge_base': False,
    }
    desktop_app._save_history(entry)


def _download_worker(job_id: str, url: str, options: dict) -> None:
    _refresh_vault()
    output_dir = desktop_app.OBSIDIAN_VIDEO_DIR

    def progress(payload: dict) -> None:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if not job:
                return
            job['stage'] = payload.get('stage') or job.get('stage', '正在下载')
            if payload.get('progress') is not None:
                job['progress'] = payload.get('progress')

    try:
        result = download_video(
            url,
            str(output_dir),
            proxy=options.get('proxy') or None,
            progress_callback=progress,
        )
        if result.get('success'):
            _save_download_result(job_id, url, result)
            with _jobs_lock:
                _jobs[job_id].update(status='completed', stage='下载完成', progress=100, title=(result.get('metadata') or {}).get('title'))
        else:
            with _jobs_lock:
                _jobs[job_id].update(status='failed', stage='下载失败', error=result.get('error') or '下载失败')
    except Exception as exc:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].update(status='failed', stage='下载失败', error=str(exc))


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


class MobileWebHandler(BaseHTTPRequestHandler):
    server_version = 'VideoLinkMobile/1.0'

    def log_message(self, format: str, *args) -> None:
        # Keep the terminal useful while still recording requests that fail.
        if self.command != 'GET' or self.path.startswith('/api/'):
            super().log_message(format, *args)

    @property
    def access_token(self) -> str:
        return str(getattr(self.server, 'access_token', '') or '')

    def _authorized(self) -> bool:
        if not self.access_token or not self.path.startswith('/api/'):
            return True
        supplied = self.headers.get('X-Mobile-Token', '')
        if not supplied:
            supplied = parse_qs(urlparse(self.path).query).get('token', [''])[0]
        return secrets.compare_digest(supplied, self.access_token)

    def _send(self, status: int, value: object, content_type: str = 'application/json; charset=utf-8') -> None:
        body = value if isinstance(value, bytes) else _json_bytes(value)
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get('Content-Length', '0') or 0)
        if length > MAX_BODY_BYTES:
            raise ValueError('请求内容过大')
        raw = self.rfile.read(length) if length else b'{}'
        value = json.loads(raw.decode('utf-8'))
        if not isinstance(value, dict):
            raise ValueError('请求格式错误')
        return value

    def do_GET(self) -> None:
        if self.path in ('/', '/index.html'):
            try:
                self._send(HTTPStatus.OK, WEB_PAGE.read_bytes(), 'text/html; charset=utf-8')
            except OSError:
                self._send(HTTPStatus.NOT_FOUND, {'error': '手机页面不存在'})
            return
        if self.path == '/manifest.json':
            try:
                self._send(HTTPStatus.OK, WEB_MANIFEST.read_bytes(), 'application/manifest+json')
            except OSError:
                self._send(HTTPStatus.NOT_FOUND, {'error': '应用清单不存在'})
            return
        if self.path == '/service-worker.js':
            try:
                self._send(HTTPStatus.OK, WEB_SERVICE_WORKER.read_bytes(), 'application/javascript; charset=utf-8')
            except OSError:
                self._send(HTTPStatus.NOT_FOUND, {'error': '离线缓存脚本不存在'})
            return
        if self.path == '/app-icon.svg':
            try:
                self._send(HTTPStatus.OK, WEB_ICON.read_bytes(), 'image/svg+xml')
            except OSError:
                self._send(HTTPStatus.NOT_FOUND, {'error': '应用图标不存在'})
            return
        if not self._authorized():
            self._send(HTTPStatus.UNAUTHORIZED, {'error': '需要访问密码'})
            return
        path = urlparse(self.path).path
        if path == '/api/status':
            config = desktop_app._ai_config()
            with _jobs_lock:
                jobs = [_job_view(job) for job in _jobs.values()]
            self._send(HTTPStatus.OK, {
                'ok': True,
                'ai_configured': desktop_app._ai_is_configured(config),
                'jobs': jobs,
                'vault_name': desktop_app.OBSIDIAN_VAULT.name,
            })
        elif path == '/api/jobs':
            with _jobs_lock:
                self._send(HTTPStatus.OK, [_job_view(job) for job in _jobs.values()])
        elif path == '/api/history':
            self._send(HTTPStatus.OK, _history_view())
        else:
            self._send(HTTPStatus.NOT_FOUND, {'error': '接口不存在'})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send(HTTPStatus.UNAUTHORIZED, {'error': '需要访问密码'})
            return
        path = urlparse(self.path).path
        try:
            data = self._read_json()
            if path == '/api/download':
                self._start_download(data)
            elif path == '/api/ask':
                self._ask_ai(data)
            else:
                self._send(HTTPStatus.NOT_FOUND, {'error': '接口不存在'})
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(HTTPStatus.BAD_REQUEST, {'error': str(exc)})

    def _start_download(self, data: dict) -> None:
        url = str(data.get('url') or '').strip()
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            self._send(HTTPStatus.BAD_REQUEST, {'error': '请输入有效的视频链接'})
            return
        options = {'proxy': str(data.get('proxy') or '').strip()}
        job_id = uuid.uuid4().hex
        job = {'id': job_id, 'url': url, 'status': 'queued', 'stage': '等待下载', 'progress': 0}
        with _jobs_lock:
            _jobs[job_id] = job
        threading.Thread(target=_download_worker, args=(job_id, url, options), daemon=True).start()
        self._send(HTTPStatus.ACCEPTED, _job_view(job))

    def _ask_ai(self, data: dict) -> None:
        question = str(data.get('question') or '').strip()
        if not question:
            self._send(HTTPStatus.BAD_REQUEST, {'error': '请输入问题'})
            return
        answer = desktop_app._query_ai_database(question)
        try:
            desktop_app._save_conversation_memory(question, answer)
        except OSError:
            pass
        self._send(HTTPStatus.OK, {'answer': answer})


def _local_addresses(port: int) -> list[str]:
    addresses = ['127.0.0.1']
    try:
        addresses.extend(sorted({item[4][0] for item in socket.getaddrinfo(socket.gethostname(), port, type=socket.SOCK_STREAM)}))
    except OSError:
        pass
    return [f'http://{address}:{port}' for address in addresses]


def main() -> None:
    parser = argparse.ArgumentParser(description='手机端视频下载 Web 服务')
    parser.add_argument('--host', default=os.environ.get('MOBILE_WEB_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('MOBILE_WEB_PORT', '8765')))
    parser.add_argument('--token', default=os.environ.get('MOBILE_WEB_TOKEN', ''))
    args = parser.parse_args()
    if not (1 <= args.port <= 65535):
        parser.error('--port 必须在 1 到 65535 之间')
    server = ThreadingHTTPServer((args.host, args.port), MobileWebHandler)
    server.access_token = args.token
    print('手机 Web 界面已启动：')
    for address in _local_addresses(args.port):
        print(f'  {address}')
    if args.host not in ('127.0.0.1', 'localhost', '::1'):
        if args.token:
            print('已启用访问密码保护。')
        else:
            print('警告：当前未设置访问密码，仅建议在可信局域网使用。')
    print('按 Ctrl+C 停止服务。')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
