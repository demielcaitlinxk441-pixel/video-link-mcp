"""
Video download module.
Uses yt-dlp to download video + audio + subtitles.
Handles subtitle file discovery across different yt-dlp naming conventions.
Supports cookies (from browser or file) and proxy for platforms like Douyin.
WeChat Channels (视频号) supports two modes:
  1. Direct API calls (if WECHAT_CHANNELS_YUANBAO_COOKIE is set) — no third-party dependency
  2. Worker API fallback (sph.litao.workers.dev) — out-of-box, but relies on third-party service
"""

import os
import re
import sys
import subprocess
import tempfile
import glob
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse


def _is_wechat_channels(url: str) -> bool:
    """Check if URL is a WeChat Channels (视频号) link."""
    from .wechat_channels_api import is_wechat_channels
    return is_wechat_channels(url)


def _handle_wechat_channels_download(url: str, output_dir: str, **kwargs) -> dict:
    """
    Fully automated WeChat Channels video download.
    Uses direct API calls (if Yuanbao cookie available) or Worker API fallback.
    """
    from .wechat_channels_api import download_video as api_download
    yuanbao_cookie = kwargs.get('yuanbao_cookie')
    return api_download(url, output_dir, yuanbao_cookie=yuanbao_cookie)


def _handle_wechat_channels_info(url: str, **kwargs) -> dict:
    """Get WeChat Channels video info via API."""
    from .wechat_channels_api import get_video_info
    yuanbao_cookie = kwargs.get('yuanbao_cookie')
    return get_video_info(url, yuanbao_cookie=yuanbao_cookie)


def _run_playwright_intercept(url: str, output_dir: Optional[str]) -> dict:
    """Run Playwright's synchronous API outside an MCP asyncio loop.

    FastMCP invokes tools while an asyncio loop is active. Playwright's
    ``sync_playwright`` intentionally rejects that situation, so the fallback
    must execute in a separate worker thread.
    """
    from .playwright_downloader import intercept_download

    with ThreadPoolExecutor(
        max_workers=1, thread_name_prefix='playwright-intercept'
    ) as executor:
        return executor.submit(intercept_download, url, output_dir).result()


def find_ffmpeg() -> Optional[str]:
    """Locate the ffmpeg executable on the system."""
    # 1) Check PATH
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return 'ffmpeg'
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 2) Common Windows locations
    if sys.platform == 'win32':
        search_bases = [
            os.environ.get('PROGRAMFILES', ''),
            os.environ.get('LOCALAPPDATA', ''),
            os.environ.get('USERPROFILE', ''),
            'C:\\ffmpeg',
            'C:\\Program Files\\ffmpeg',
        ]
        for base in search_bases:
            if not base:
                continue
            for pattern in (
                os.path.join(base, 'bin', 'ffmpeg.exe'),
                os.path.join(base, 'ffmpeg.exe'),
            ):
                if os.path.exists(pattern):
                    return pattern
            # Recursive search
            for match in glob.glob(
                os.path.join(base, '**', 'ffmpeg.exe'), recursive=True
            ):
                return match

    return None


def _normalize_douyin_url(url: str) -> str:
    """
    Convert various Douyin URL formats to a canonical video URL.

    Supported formats:
      - https://www.douyin.com/video/<id>
      - https://www.douyin.com/jingxuan?modal_id=<id>
      - https://v.douyin.com/<shortcode>
      - https://www.iesdouyin.com/share/video/<id>
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower().lstrip('www.')
    path = parsed.path
    query = parse_qs(parsed.query)

    # modal_id form: /jingxuan?modal_id=xxx
    if 'modal_id' in query:
        video_id = query['modal_id'][0]
        return f'https://www.douyin.com/video/{video_id}'

    # iesdouyin share form
    m = re.search(r'/share/video/(\d+)', path)
    if m:
        return f'https://www.douyin.com/video/{m.group(1)}'

    # already canonical
    if re.search(r'/video/\d+', path):
        return url

    # short link v.douyin.com/xxxxx — yt-dlp can usually resolve these,
    # but we keep them as-is here.
    return url


def _normalize_xiaohongshu_url(url: str) -> str:
    """
    Normalize Xiaohongshu URLs.

    Supported formats:
      - https://www.xiaohongshu.com/explore/<id>
      - https://www.xiaohongshu.com/note/<id>
      - https://www.xiaohongshu.com/discovery/item/<id>
      - https://xhslink.com/<shortcode>  (short link, keep as-is for redirect)
    """
    return url  # Xiaohongshu URLs are already handled well by yt-dlp as-is


def normalize_url(url: str) -> str:
    """Normalize a video URL to a form most friendly for yt-dlp."""
    lower = url.lower()
    if 'douyin' in lower:
        return _normalize_douyin_url(url)
    if 'xiaohongshu' in lower or 'xhslink' in lower:
        return _normalize_xiaohongshu_url(url)
    return url


def _build_ydl_opts(
    base_opts: dict,
    ffmpeg_path: Optional[str],
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    proxy: Optional[str] = None,
) -> dict:
    """Merge cookie/proxy/ffmpeg options into yt-dlp options."""
    opts = dict(base_opts)

    if ffmpeg_path and ffmpeg_path != 'ffmpeg':
        opts['ffmpeg_location'] = os.path.dirname(ffmpeg_path)

    if cookies_from_browser:
        # yt-dlp accepts: BROWSER[+KEYRING][:PROFILE]
        # e.g. chrome, edge, firefox, safari
        opts['cookiesfrombrowser'] = (cookies_from_browser,)

    if cookies_file and os.path.exists(cookies_file):
        opts['cookiefile'] = cookies_file

    if proxy:
        opts['proxy'] = proxy

    return opts


def get_video_info(
    url: str,
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    proxy: Optional[str] = None,
    yuanbao_cookie: Optional[str] = None,
) -> dict:
    """Extract video metadata without downloading."""
    # WeChat Channels: use direct API or Worker API
    if _is_wechat_channels(url):
        return _handle_wechat_channels_info(url, yuanbao_cookie=yuanbao_cookie)

    try:
        import yt_dlp
    except ImportError:
        return {
            'success': False,
            'error': 'yt-dlp is not installed. Run: pip install yt-dlp',
        }

    url = normalize_url(url)

    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
    }

    ffmpeg_path = find_ffmpeg()
    ydl_opts = _build_ydl_opts(
        base_opts, ffmpeg_path, cookies_from_browser, cookies_file, proxy
    )

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'success': True,
                'metadata': {
                    'title': info.get('title', ''),
                    'duration': info.get('duration', 0),
                    'duration_string': info.get('duration_string', ''),
                    'description': (info.get('description') or '')[:5000],
                    'uploader': info.get('uploader', ''),
                    'channel': info.get('channel', ''),
                    'upload_date': info.get('upload_date', ''),
                    'view_count': info.get('view_count', 0),
                    'like_count': info.get('like_count', 0),
                    'comment_count': info.get('comment_count', 0),
                    'webpage_url': info.get('webpage_url', url),
                    'extractor': info.get('extractor_key', ''),
                    'thumbnail': info.get('thumbnail', ''),
                    'categories': info.get('categories', []),
                    'tags': info.get('tags', []),
                },
                'available_subtitles': list(
                    (info.get('subtitles') or {}).keys()
                ),
                'available_auto_subs': list(
                    (info.get('automatic_captions') or {}).keys()
                ),
            }
    except Exception as e:
        error_msg = str(e)

        # If yt-dlp fails, try Playwright to at least get the page title
        try:
            pw_result = _run_playwright_intercept(url, None)
            if pw_result.get('success'):
                return {
                    'success': True,
                    'metadata': {
                        'title': pw_result.get('metadata', {}).get('title', ''),
                        'description': pw_result.get('metadata', {}).get('description', ''),
                        'webpage_url': url,
                        'extractor': 'playwright_intercept',
                    },
                    'available_subtitles': [],
                    'available_auto_subs': [],
                    'note': 'Video info retrieved via Playwright fallback (yt-dlp failed).',
                }
        except (ImportError, RuntimeError):
            pass

        return {
            'success': False,
            'error': f'Failed to extract video info: {error_msg}',
        }


def _find_subtitle(base_without_ext: str, video_id: str, output_dir: str,
                   lang_list: list) -> tuple:
    """
    Search for subtitle files using multiple naming patterns.

    Returns (subtitle_path, subtitle_lang, is_auto_generated).
    """
    # Pattern 1: direct naming {base}.{lang}.vtt/.srt
    for lang in lang_list:
        for ext in ('.vtt', '.srt'):
            candidate = f'{base_without_ext}.{lang}{ext}'
            if os.path.exists(candidate):
                return candidate, lang, False

    # Pattern 2: auto-generated {base}.{lang}.auto.vtt
    for lang in lang_list:
        for ext in ('.vtt', '.srt'):
            candidate = f'{base_without_ext}.{lang}.auto{ext}'
            if os.path.exists(candidate):
                return candidate, lang, True

    # Pattern 3: glob search by video ID
    if video_id:
        for f in os.listdir(output_dir):
            if video_id in f and f.endswith(('.vtt', '.srt')):
                fpath = os.path.join(output_dir, f)
                detected_lang = 'unknown'
                for lang in lang_list:
                    if lang in f:
                        detected_lang = lang
                        break
                return fpath, detected_lang, '.auto.' in f

    return None, None, False


def _find_video_file(base_without_ext: str, video_id: str,
                     output_dir: str) -> Optional[str]:
    """Search for the downloaded video file."""
    for ext in ('.mp4', '.mkv', '.webm', '.avi'):
        candidate = base_without_ext + ext
        if os.path.exists(candidate):
            return candidate

    # Fallback: search by video ID
    if video_id:
        for f in os.listdir(output_dir):
            if video_id in f and any(f.endswith(e) for e in
                                     ('.mp4', '.mkv', '.webm', '.avi')):
                return os.path.join(output_dir, f)

    return None


def download_video(
    url: str,
    output_dir: str = None,
    prefer_subtitle_lang: str = 'zh-Hans,zh,en',
    cookies_from_browser: Optional[str] = None,
    cookies_file: Optional[str] = None,
    proxy: Optional[str] = None,
    yuanbao_cookie: Optional[str] = None,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> dict:
    """
    Download a video with audio and subtitles.

    Args:
        url: Video URL.
        output_dir: Directory for downloaded files (default: temp dir).
        prefer_subtitle_lang: Comma-separated preferred subtitle languages.
        cookies_from_browser: Browser name for yt-dlp to read cookies from
            (e.g. 'chrome', 'edge', 'firefox').
        cookies_file: Path to a Netscape-format cookies.txt file.
        proxy: Proxy URL, e.g. 'http://127.0.0.1:7890'.
        yuanbao_cookie: Yuanbao web cookie for WeChat Channels direct API mode.
            If not provided, checks WECHAT_CHANNELS_YUANBAO_COOKIE env var.

    Returns:
        dict with success status, file paths, subtitle text, and metadata.
    """
    if output_dir is None or output_dir == '':
        output_dir = os.path.join(tempfile.gettempdir(), 'video-link-analyzer')

    os.makedirs(output_dir, exist_ok=True)

    def report_progress(payload: dict) -> None:
        if progress_callback:
            try:
                progress_callback(payload)
            except Exception:
                pass

    # WeChat Channels: use direct API or Worker API
    if _is_wechat_channels(url):
        report_progress({'stage': '正在解析微信视频号链接'})
        result = _handle_wechat_channels_download(
            url, output_dir, yuanbao_cookie=yuanbao_cookie
        )
        report_progress({'stage': '完成' if result.get('success') else '下载失败'})
        return result

    try:
        import yt_dlp
    except ImportError:
        return {
            'success': False,
            'error': 'yt-dlp is not installed. Run: pip install yt-dlp',
        }

    url = normalize_url(url)

    ffmpeg_path = find_ffmpeg()
    lang_list = [lang.strip() for lang in prefer_subtitle_lang.split(',') if lang.strip()]

    output_template = os.path.join(
        output_dir, '%(title).80s [%(id)s].%(ext)s'
    )

    base_opts = {
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': output_template,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': lang_list,
        'subtitlesformat': 'vtt/best',
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'overwrites': False,
    }

    if progress_callback:
        def progress_hook(data: dict) -> None:
            status = data.get('status')
            if status == 'downloading':
                total = data.get('total_bytes') or data.get('total_bytes_estimate')
                downloaded = data.get('downloaded_bytes', 0)
                report_progress({
                    'stage': '正在下载',
                    'progress': round(downloaded / total * 100, 1) if total else None,
                    'downloaded_bytes': downloaded,
                    'total_bytes': total,
                    'speed': data.get('speed'),
                    'eta': data.get('eta'),
                })
            elif status == 'finished':
                report_progress({'stage': '正在合并音视频', 'progress': 100})

        base_opts['progress_hooks'] = [progress_hook]

    ydl_opts = _build_ydl_opts(
        base_opts, ffmpeg_path, cookies_from_browser, cookies_file, proxy
    )

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info for metadata + filename prediction
            info = ydl.extract_info(url, download=False)
            video_id = info.get('id', '')

            metadata = {
                'title': info.get('title', ''),
                'duration': info.get('duration', 0),
                'duration_string': info.get('duration_string', ''),
                'description': (info.get('description') or '')[:5000],
                'uploader': info.get('uploader', ''),
                'channel': info.get('channel', ''),
                'upload_date': info.get('upload_date', ''),
                'view_count': info.get('view_count', 0),
                'like_count': info.get('like_count', 0),
                'webpage_url': info.get('webpage_url', url),
                'extractor': info.get('extractor_key', ''),
                'thumbnail': info.get('thumbnail', ''),
            }

            base_filename = ydl.prepare_filename(info)
            base_without_ext = os.path.splitext(base_filename)[0]

            # Perform the actual download
            ydl.download([url])

            # Locate downloaded files
            video_path = _find_video_file(base_without_ext, video_id, output_dir)

            sub_path, sub_lang, sub_is_auto = _find_subtitle(
                base_without_ext, video_id, output_dir, lang_list
            )

            # Parse subtitle text
            subtitle_text = None
            if sub_path:
                from .subtitle_parser import parse_subtitle
                subtitle_text = parse_subtitle(sub_path)

            # Calculate file size
            file_size = 0
            if video_path and os.path.exists(video_path):
                file_size = os.path.getsize(video_path)

            return {
                'success': True,
                'video_path': video_path,
                'size': file_size,
                'subtitle_path': sub_path,
                'subtitle_text': subtitle_text,
                'subtitle_lang': sub_lang,
                'subtitle_is_auto': sub_is_auto,
                'has_subtitle': sub_path is not None and subtitle_text is not None,
                'metadata': metadata,
                'output_dir': output_dir,
                'ffmpeg_found': ffmpeg_path is not None,
                'cookies_from_browser': cookies_from_browser,
                'cookies_file': cookies_file,
                'proxy': proxy,
            }

    except Exception as e:
        error_msg = str(e)

        # ── Playwright fallback ──────────────────────────────────
        # When yt-dlp fails (cookies, anti-scraping, etc.), try the
        # Playwright intercept method as a last resort.
        # This is especially useful for Douyin / TikTok.
        try:
            report_progress({'stage': '正在使用浏览器解析视频'})
            pw_result = _run_playwright_intercept(url, output_dir)
        except ImportError:
            return {
                'success': False,
                'error': f'Download failed: {error_msg}',
                'output_dir': output_dir,
                'cookies_from_browser': cookies_from_browser,
                'cookies_file': cookies_file,
                'proxy': proxy,
            }
        except Exception as pw_error:
            pw_result = {
                'success': False,
                'error': f'Playwright fallback failed: {pw_error}',
            }
        if pw_result.get('success'):
            report_progress({'stage': '完成', 'progress': 100})
            # Build a result dict compatible with the yt-dlp path
            return {
                'success': True,
                'video_path': pw_result.get('video_path'),
                'subtitle_path': None,
                'subtitle_text': None,
                'subtitle_lang': None,
                'subtitle_is_auto': False,
                'has_subtitle': False,
                'metadata': {
                    'title': pw_result.get('metadata', {}).get('title', ''),
                    'description': pw_result.get('metadata', {}).get('description', ''),
                    'source_url': url,
                    'video_source_url': pw_result.get('metadata', {}).get('video_source_url', ''),
                },
                'output_dir': output_dir,
                'ffmpeg_found': ffmpeg_path is not None,
                'download_method': 'playwright_intercept',
                'yt_dlp_error': error_msg,
                'cookies_from_browser': cookies_from_browser,
                'cookies_file': cookies_file,
                'proxy': proxy,
            }

        # Both yt-dlp and Playwright failed
        return {
            'success': False,
            'error': f'yt-dlp: {error_msg} | playwright: {pw_result.get("error", "unknown")}',
            'output_dir': output_dir,
            'cookies_from_browser': cookies_from_browser,
            'cookies_file': cookies_file,
            'proxy': proxy,
        }
