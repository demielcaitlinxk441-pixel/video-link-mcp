"""Resumable HTTP downloads shared by direct and browser fallback paths."""

import os
import time
import urllib.error
import urllib.request
from typing import Callable, Optional


class DownloadCancelled(Exception):
    """Raised when the caller cancels an active download."""


class DownloadHTTPError(OSError):
    """HTTP failure with stable status and attempt metadata."""

    def __init__(self, status: int, attempts: int, message: str):
        super().__init__(f'HTTP Error {status}: {message}')
        self.status = status
        self.attempts = attempts


def _retry_delay(status: int | None, attempt: int) -> int:
    if status == 429:
        return (5, 15, 30)[min(attempt - 1, 2)]
    return min(2 ** attempt, 16)


def _wait_before_retry(seconds: int, *, attempt: int, max_attempts: int,
                       progress_callback=None, cancel_callback=None) -> None:
    for remaining in range(seconds, 0, -1):
        if cancel_callback and cancel_callback():
            raise DownloadCancelled('下载已取消')
        if progress_callback:
            progress_callback({
                'stage': f'等待重试：还剩 {remaining} 秒（{attempt + 1}/{max_attempts}）',
                'progress': None, 'retry_in': remaining, 'attempt': attempt + 1,
            })
        time.sleep(1)


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
    timeout: int = 30,
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
                                'temporary_file': part_path,
                            })
                if total and downloaded < total:
                    raise OSError(
                        f'连接提前结束：已下载 {downloaded} 字节，应为 {total} 字节'
                    )
            os.replace(part_path, target_path)
            return downloaded
        except DownloadCancelled:
            raise
        except urllib.error.HTTPError as exc:
            last_error = exc
            status = int(exc.code)
            if status in {401, 403, 412}:
                raise DownloadHTTPError(status, attempt, '授权失败，请重新完成平台授权') from exc
            retryable = status == 429 or status in {500, 502, 503, 504}
            if not retryable or attempt >= max_attempts:
                raise DownloadHTTPError(status, attempt, str(exc.reason or exc)) from exc
            _wait_before_retry(
                _retry_delay(status, attempt), attempt=attempt, max_attempts=max_attempts,
                progress_callback=progress_callback, cancel_callback=cancel_callback,
            )
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt < max_attempts:
                _wait_before_retry(
                    _retry_delay(None, attempt), attempt=attempt, max_attempts=max_attempts,
                    progress_callback=progress_callback, cancel_callback=cancel_callback,
                )

    raise OSError(f'下载重试 {max_attempts} 次后仍然失败：{last_error}')
