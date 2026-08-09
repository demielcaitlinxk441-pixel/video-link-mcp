"""Resumable HTTP downloads shared by direct and browser fallback paths."""

import os
import time
import urllib.error
import urllib.request
from typing import Callable, Optional


class DownloadCancelled(Exception):
    """Raised when the caller cancels an active download."""


def _total_size(response, existing: int) -> int:
    content_range = response.headers.get('Content-Range', '')
    if '/' in content_range:
        try:
            return int(content_range.rsplit('/', 1)[1])
        except ValueError:
            pass
    try:
        length = int(response.headers.get('Content-Length') or 0)
    except ValueError:
        length = 0
    return length + existing if response.status == 206 else length


def download_with_resume(
    url: str,
    target_path: str,
    *,
    headers: Optional[dict] = None,
    progress_callback: Optional[Callable[[dict], None]] = None,
    cancel_callback: Optional[Callable[[], bool]] = None,
    stage: str = '正在下载',
    timeout: int = 120,
    max_attempts: int = 3,
) -> int:
    """Download to a .part file, retry failures, and resume with HTTP Range."""
    part_path = f'{target_path}.part'
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        if cancel_callback and cancel_callback():
            raise DownloadCancelled('下载已取消')

        existing = os.path.getsize(part_path) if os.path.exists(part_path) else 0
        request_headers = dict(headers or {})
        if existing:
            request_headers['Range'] = f'bytes={existing}-'
        request = urllib.request.Request(url, headers=request_headers)

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                resumed = existing > 0 and response.status == 206
                if not resumed:
                    existing = 0
                total = _total_size(response, existing)
                downloaded = existing
                mode = 'ab' if resumed else 'wb'
                with open(part_path, mode) as output:
                    while True:
                        if cancel_callback and cancel_callback():
                            raise DownloadCancelled('下载已取消')
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback({
                                'stage': stage,
                                'progress': min(99, round(downloaded * 100 / total, 1)) if total else None,
                                'downloaded_bytes': downloaded,
                                'total_bytes': total,
                                'attempt': attempt,
                                'resumed': resumed,
                            })
                if total and downloaded < total:
                    raise OSError(
                        f'连接提前结束：已下载 {downloaded} 字节，应为 {total} 字节'
                    )
            os.replace(part_path, target_path)
            return downloaded
        except DownloadCancelled:
            raise
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt < max_attempts:
                if progress_callback:
                    progress_callback({
                        'stage': f'网络中断，正在重试（{attempt + 1}/{max_attempts}）',
                        'progress': None,
                        'attempt': attempt + 1,
                    })
                time.sleep(min(attempt, 2))

    raise OSError(f'下载重试 {max_attempts} 次后仍然失败：{last_error}')
