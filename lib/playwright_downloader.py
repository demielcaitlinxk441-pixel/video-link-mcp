"""
Playwright-based video downloader — fallback for platforms where yt-dlp fails.

Strategy:
  1. Launch a headless Chromium browser
  2. Navigate to the video page
  3. Intercept all network responses, filter for real video content URLs
  4. Download the largest/highest-quality video file directly via HTTP

This bypasses yt-dlp entirely, so it works on platforms with aggressive
anti-scraping (Douyin, TikTok) without needing cookies or browser lock access.
"""

import os
import re
import tempfile
import time
import urllib.request
from urllib.parse import urlparse
from typing import Callable, Optional

# Output directory defaults to system temp
OUTPUT_DIR = os.path.join(tempfile.gettempdir(), 'video-link-analyzer')

UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/150.0.0.0 Safari/537.36'
)

# Domains that serve actual video content
VIDEO_CONTENT_DOMAINS = [
    'douyinvod.com',
    'bytecdntp.com',
    'bytecdn.cn',
    'douyincdn.com',
    'aweme.snssdk.com',
    'api.amemv.com',
    'tiktokcdn.com',
    'tiktokv.com',
    'byteoversea.com',
    # Xiaohongshu video CDN
    'xhscdn.com',
    'sns-video',
    # Kuaishou video CDN
    'kwaicdn.com',
    'kwimgs.com',
    'ksapisrv.com',
    'yximgs.com',
    'gifshow.com',
]

# Domains that serve static/effect assets (skip these)
STATIC_ASSET_DOMAINS = [
    'douyinstatic.com',
    'byteeffecttos.com',
    'lf-cdn-tos',
    'lf-effectcdn',
    'byteimg.com',
    # Xiaohongshu image CDN
    'sns-img',
]


def is_real_video_url(url: str) -> bool:
    """Check if a URL is likely to be a real video content URL (not a static asset)."""
    lower = url.lower()
    parsed = urlparse(lower)
    host = parsed.netloc

    # Skip static asset domains
    for static in STATIC_ASSET_DOMAINS:
        if static in host:
            return False

    # Check if it's a known video content domain
    for vdomain in VIDEO_CONTENT_DOMAINS:
        if vdomain in host:
            return True

    # Check for .mp4 in path (but not on static asset domains)
    if '.mp4' in lower and '/video/' in lower:
        return True

    # Check for video play API endpoints
    if 'aweme/v1/play' in lower or '/play/' in lower:
        return True

    return False


def _sanitize_filename(title: str, max_len: int = 80) -> str:
    """Create a safe filename from a title string."""
    safe = ''.join(c for c in title if c.isalnum() or c in ' _-')[:max_len].strip()
    return safe if safe else 'video'


def _download_file(
    video_url: str,
    title: str,
    output_dir: str,
    referer: str = 'https://www.douyin.com/',
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Download a video file directly from its URL."""
    os.makedirs(output_dir, exist_ok=True)
    safe_title = _sanitize_filename(title)
    output_path = os.path.join(output_dir, f'{safe_title}.mp4')

    req = urllib.request.Request(video_url, headers={
        'User-Agent': UA,
        'Referer': referer,
        'Accept': '*/*',
        'Range': 'bytes=0-',
    })

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get('Content-Length', 0))
            if resp.status in (206,) and total:
                total += 1
            downloaded = 0
            last_progress = -1
            with open(output_path, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total:
                        progress = min(99, int(downloaded * 100 / total))
                        if progress != last_progress:
                            last_progress = progress
                            progress_callback({
                                'stage': '正在下载视频',
                                'progress': progress,
                                'downloaded_bytes': downloaded,
                                'total_bytes': total,
                            })
        size = os.path.getsize(output_path)
        return {'success': True, 'video_path': output_path, 'size': size}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def intercept_download(
    url: str,
    output_dir: Optional[str] = None,
    allow_interactive_verification: bool = False,
    progress_callback: Optional[Callable[[dict], None]] = None,
) -> dict:
    """
    Use Playwright to intercept video network requests and download directly.

    Supports Douyin, TikTok, and Xiaohongshu. For Xiaohongshu, uses a
    mobile user agent and extracts video URLs from both network intercepts
    and page JavaScript data.

    Args:
        url: Video page URL (e.g. Douyin short link, Xiaohongshu note URL).
        output_dir: Directory to save the video. Defaults to system temp.

    Returns:
        dict with:
          - success: bool
          - video_path: str (on success)
          - size: int (file size in bytes, on success)
          - metadata: dict (title, description, source_url)
          - error: str (on failure)
          - method: "playwright_intercept"
    """
    if output_dir is None or output_dir == '':
        output_dir = OUTPUT_DIR

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            'success': False,
            'error': 'Playwright is not installed. Run: pip install playwright && python -m playwright install chromium',
            'method': 'playwright_intercept',
        }

    # Detect platform and configure accordingly
    is_xhs = 'xiaohongshu' in url.lower() or 'xhslink' in url.lower()
    is_douyin = 'douyin' in url.lower() or 'iesdouyin' in url.lower()
    is_kuaishou = 'kuaishou.com' in url.lower() or 'gifshow.com' in url.lower()

    if is_xhs:
        # Xiaohongshu mobile web is more accessible (no login wall)
        user_agent = (
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
            'AppleWebKit/605.1.15 (KHTML, like Gecko) '
            'Version/17.0 Mobile/15E148 Safari/604.1'
        )
        viewport = {'width': 390, 'height': 844}
        referer = 'https://www.xiaohongshu.com/'
    elif is_kuaishou:
        # 快手会对无头浏览器直接返回滑块验证码。使用可见窗口，让用户自行
        # 完成一次平台验证；不会尝试绕过验证。
        user_agent = UA
        viewport = {'width': 1280, 'height': 800}
        referer = 'https://www.kuaishou.com/'
    else:
        user_agent = UA
        viewport = {'width': 1920, 'height': 1080}
        referer = 'https://www.douyin.com/'

    all_video_urls = []
    video_src_urls = []
    page_title = ''
    page_description = ''
    page_html = ''

    with sync_playwright() as p:
        interactive_kuaishou = is_kuaishou and allow_interactive_verification
        launch_options = {'headless': not interactive_kuaishou}
        if interactive_kuaishou:
            # 快手会拦截 Playwright 附带的 Chromium（版本通常落后于本机
            # Chrome）。实测新版 Chrome 可以完成快手的此类页面访问，
            # 因此优先使用 Chrome；Edge 只作为后备。
            try:
                browser = p.chromium.launch(channel='chrome', **launch_options)
            except Exception:
                try:
                    browser = p.chromium.launch(channel='msedge', **launch_options)
                except Exception:
                    browser = p.chromium.launch(**launch_options)
        else:
            browser = p.chromium.launch(**launch_options)
        context = browser.new_context(
            user_agent=user_agent,
            viewport=viewport,
            locale='zh-CN',
        )
        page = context.new_page()

        def handle_response(response):
            resp_url = response.url
            lower = resp_url.lower()

            # Broaden interception for XHS: also catch sns-video URLs and API responses
            catch_patterns = ['.mp4', '.m3u8', 'video', 'aweme/v1/play', '/play/']
            if is_xhs:
                catch_patterns.extend(['sns-video', 'xhscdn', '/api/sns/web/v1/feed'])
            if is_kuaishou:
                catch_patterns.extend(['kwaicdn', 'kwimgs', 'ksapisrv', 'yximgs', 'gifshow', '/photo/play'])

            if any(ext in lower for ext in catch_patterns):
                content_type = response.headers.get('content-type', '')
                content_length = response.headers.get('content-length', '0')
                try:
                    cl = int(content_length)
                except (ValueError, TypeError):
                    cl = 0

                # For XHS API responses, try to extract video URL from JSON
                if 'json' in content_type and is_xhs:
                    try:
                        body = response.json()
                        # XHS API may return video URL in various nested fields
                        _extract_xhs_video_urls(body, all_video_urls)
                    except Exception:
                        pass

                if 'video' in content_type or '.mp4' in lower or 'play' in lower or 'sns-video' in lower:
                    is_real = is_real_video_url(resp_url)
                    entry = {
                        'url': resp_url,
                        'content_length': cl,
                        'content_type': content_type,
                        'is_real_video': is_real,
                        'status': response.status,
                    }
                    if entry not in all_video_urls:
                        all_video_urls.append(entry)

        page.on('response', handle_response)

        # Visit the video page
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
        except Exception:
            pass

        # Wait for page to load and video to start. Kuaishou may show a
        # “browser version too low” overlay. Keep its visible window open so
        # the user can manually select the official “retry” action; do not
        # attempt to dismiss or bypass the platform prompt programmatically.
        if is_kuaishou and allow_interactive_verification:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                try:
                    retry_visible = page.get_by_text('点击重试', exact=True).is_visible()
                except Exception:
                    retry_visible = False
                if (
                    'captcha' not in page.url.lower()
                    and page.query_selector('video')
                    and not retry_visible
                ):
                    break
                page.wait_for_timeout(1000)
        else:
            page.wait_for_timeout(8000)

        # Try to click play button (different selectors for different platforms)
        try:
            if is_xhs:
                play_btn = page.query_selector('video, .play-btn, [class*="play"]')
            else:
                play_btn = page.query_selector('video, .xgplayer-start, [data-e2e="video-play-btn"]')
            if play_btn:
                play_btn.click()
                page.wait_for_timeout(5000)
        except Exception:
            pass

        # Get page metadata. Kuaishou may close its challenge page while the
        # user is verifying, so surface a useful failure instead of leaking a
        # Playwright TargetClosedError to the desktop app.
        try:
            page_title = page.title()
        except Exception:
            if is_kuaishou:
                return {
                    'success': False,
                    'error': '快手窗口已关闭，未能完成操作。请重新下载，在弹出窗口点击“点击重试”，并保持窗口打开。',
                    'metadata': {'title': '', 'description': '', 'source_url': url},
                    'method': 'playwright_intercept',
                }
            raise

        # Try to get description (platform-specific selectors)
        try:
            if is_xhs:
                desc_el = page.query_selector('#detail-desc, .note-text, .desc, [class*="title"]')
            else:
                desc_el = page.query_selector('[data-e2e="video-desc"], .video-info-detail .title')
            if desc_el:
                page_description = desc_el.inner_text()
        except Exception:
            pass

        # Get video src directly from the video element
        try:
            video_el = page.query_selector('video')
            if video_el:
                src = video_el.get_attribute('src')
                if src:
                    video_src_urls.append(src)
                # Also try <source> tags
                sources = video_el.query_selector_all('source')
                for s in sources:
                    src = s.get_attribute('src')
                    if src:
                        video_src_urls.append(src)
        except Exception:
            pass

        # For XHS: try to extract video URL from page HTML/JS
        if is_xhs:
            try:
                page_html = page.content()
                _extract_xhs_video_from_html(page_html, all_video_urls)
            except Exception:
                pass

        browser.close()

    # Filter and sort: prefer real video URLs, sort by size (largest first)
    real_urls = [e for e in all_video_urls if e.get('is_real_video')]
    static_urls = [e for e in all_video_urls if not e.get('is_real_video')]

    # Add video.src URLs as candidates too
    for src in video_src_urls:
        if is_real_video_url(src) or '.mp4' in src.lower():
            real_urls.append({'url': src, 'content_length': 0, 'is_real_video': True})

    # Sort by content_length descending (largest video first)
    real_urls.sort(key=lambda x: x.get('content_length', 0), reverse=True)

    if not real_urls:
        # Fallback: try static URLs that have significant size (>500KB)
        big_statics = [e for e in static_urls if e.get('content_length', 0) > 500000]
        if big_statics:
            real_urls = big_statics

    if not real_urls:
        if is_kuaishou:
            return {
                'success': False,
                'error': '快手没有返回视频地址。请重新下载，在弹出窗口点击“点击重试”，等待页面加载后保持窗口打开。',
                'metadata': {'title': page_title, 'description': page_description, 'source_url': url},
                'method': 'playwright_intercept',
            }
        return {
            'success': False,
            'error': 'No video URL intercepted. The page may require JavaScript interaction or login.',
            'metadata': {'title': page_title, 'description': page_description, 'source_url': url},
            'method': 'playwright_intercept',
        }

    # Try each real video URL until one works
    for entry in real_urls:
        vurl = entry['url']
        result = _download_file(
            vurl, page_title or 'video', output_dir, referer=referer,
            progress_callback=progress_callback,
        )
        if result.get('success'):
            # Verify the downloaded file is not too small (likely a placeholder)
            min_size = 200_000  # 200KB threshold
            if result['size'] < min_size and len(real_urls) > 1:
                # Too small, skip to next URL
                continue

            result['metadata'] = {
                'title': page_title,
                'description': page_description,
                'source_url': url,
                'video_source_url': vurl,
            }
            result['method'] = 'playwright_intercept'
            return result

    return {
        'success': False,
        'error': 'All intercepted video URLs failed to download.',
        'metadata': {'title': page_title, 'description': page_description, 'source_url': url},
        'method': 'playwright_intercept',
    }


def _extract_xhs_video_urls(data, url_list: list):
    """Recursively search a JSON response for Xiaohongshu video URLs."""
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, str) and ('sns-video' in val.lower() or 'xhscdn' in val.lower() or ('.mp4' in val.lower() and 'http' in val.lower())):
                entry = {
                    'url': val,
                    'content_length': 0,
                    'content_type': 'video/mp4',
                    'is_real_video': True,
                    'status': 200,
                }
                if entry not in url_list:
                    url_list.append(entry)
            else:
                _extract_xhs_video_urls(val, url_list)
    elif isinstance(data, list):
        for item in data:
            _extract_xhs_video_urls(item, url_list)


def _extract_xhs_video_from_html(html: str, url_list: list):
    """Extract video URLs from Xiaohongshu page HTML (script tags, JSON data)."""
    # Look for video URLs in script content
    # XHS embeds initial state in window.__INITIAL_STATE__ or similar
    patterns = [
        r'"(https?://[^"]*sns-video[^"]*\.mp4[^"]*)"',
        r'"(https?://[^"]*xhscdn[^"]*\.mp4[^"]*)"',
        r'"(https?://[^"]*sns-video[^"]*)"',
        r'"play_url":\s*"(https?://[^"]*)"',
        r'"origin_video_key":\s*"(https?://[^"]*)"',
        r'"url":\s*"(https?://[^"]*\.mp4[^"]*)"',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html, re.IGNORECASE)
        for match in matches:
            entry = {
                'url': match.replace('\\u002F', '/').replace('\\/', '/'),
                'content_length': 0,
                'content_type': 'video/mp4',
                'is_real_video': True,
                'status': 200,
            }
            if entry not in url_list:
                url_list.append(entry)
