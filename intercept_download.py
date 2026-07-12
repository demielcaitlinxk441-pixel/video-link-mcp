#!/usr/bin/env python
"""
Download Douyin video by intercepting network requests with Playwright.

Instead of relying on yt-dlp (which has cookie issues with Douyin), this script:
  1. Opens the Douyin video page in a headless browser
  2. Intercepts all network requests for video/media files
  3. Filters out static assets, keeps real video content URLs
  4. Downloads the largest/highest-quality video file directly

Also captures the page title and description for metadata.
"""

import os
import sys
import json
import time
import tempfile
import urllib.request
from urllib.parse import urlparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

OUTPUT_DIR = os.path.join(tempfile.gettempdir(), 'video-link-analyzer')
os.makedirs(OUTPUT_DIR, exist_ok=True)

UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/130.0.0.0 Safari/537.36'
)

# Domains that serve actual video content
VIDEO_CONTENT_DOMAINS = [
    'douyinvod.com',
    'bytecdntp.com',
    'bytecdn.cn',
    'douyincdn.com',
    'aweme.snssdk.com',
    'api.amemv.com',
]

# Domains that serve static/effect assets (skip these)
STATIC_ASSET_DOMAINS = [
    'douyinstatic.com',
    'byteeffecttos.com',
    'lf-cdn-tos',
    'lf-effectcdn',
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


def download_video_direct(video_url: str, title: str = 'douyin_video') -> dict:
    """Download a video file directly from its URL."""
    safe_title = ''.join(c for c in title if c.isalnum() or c in ' _-')[:80].strip()
    if not safe_title:
        safe_title = 'douyin_video'

    output_path = os.path.join(OUTPUT_DIR, f'{safe_title}.mp4')

    req = urllib.request.Request(video_url, headers={
        'User-Agent': UA,
        'Referer': 'https://www.douyin.com/',
        'Accept': '*/*',
        'Range': 'bytes=0-',
    })

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get('Content-Length', 0))
            # Handle 206 Partial Content
            if resp.status == 206 and total:
                total += 1  # Range request returns total-1
            downloaded = 0
            with open(output_path, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded * 100 // total
                        print(f'\r  Downloading: {pct}% ({downloaded//1024}KB/{total//1024}KB)', end='', flush=True)
            print()
        size = os.path.getsize(output_path)
        return {'success': True, 'video_path': output_path, 'size': size}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def intercept_and_download(url: str) -> dict:
    """Use Playwright to intercept video network requests and download directly."""
    from playwright.sync_api import sync_playwright

    all_video_urls = []  # (url, content_length, is_real_video)
    video_src_urls = []
    page_title = ''
    page_description = ''

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=UA,
            viewport={'width': 1920, 'height': 1080},
            locale='zh-CN',
        )
        page = context.new_page()

        def handle_response(response):
            resp_url = response.url
            lower = resp_url.lower()

            # Capture all potential video URLs with metadata
            if any(ext in lower for ext in ['.mp4', '.m3u8', 'video', 'aweme/v1/play', '/play/']):
                content_type = response.headers.get('content-type', '')
                content_length = response.headers.get('content-length', '0')
                try:
                    cl = int(content_length)
                except:
                    cl = 0

                if 'video' in content_type or '.mp4' in lower or 'play' in lower:
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
                        tag = 'REAL' if is_real else 'static'
                        print(f'  [ intercept/{tag} ] {cl//1024}KB - {resp_url[:100]}...')

        page.on('response', handle_response)

        # Visit the video page
        print(f'[1/3] Opening video page: {url}')
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
        except Exception as e:
            print(f'  Navigation warning: {e}')

        # Wait for page to load and video to start
        print('[2/3] Waiting for video to load...')
        page.wait_for_timeout(8000)

        # Try to click play button
        try:
            play_btn = page.query_selector('video, .xgplayer-start, [data-e2e="video-play-btn"]')
            if play_btn:
                play_btn.click()
                page.wait_for_timeout(5000)
        except:
            pass

        # Get page metadata
        page_title = page.title()
        print(f'  Page title: {page_title}')

        # Try to get description
        try:
            desc_el = page.query_selector('[data-e2e="video-desc"], .video-info-detail .title')
            if desc_el:
                page_description = desc_el.inner_text()
                print(f'  Description: {page_description[:100]}')
        except:
            pass

        # Get video src directly from the video element
        try:
            video_el = page.query_selector('video')
            if video_el:
                src = video_el.get_attribute('src')
                if src:
                    video_src_urls.append(src)
                    print(f'  [ video.src ] {src[:100]}...')
        except:
            pass

        browser.close()

    # Filter and sort: prefer real video URLs, sort by size (largest first)
    real_urls = [e for e in all_video_urls if e['is_real_video']]
    static_urls = [e for e in all_video_urls if not e['is_real_video']]

    # Add video.src URLs as candidates too
    for src in video_src_urls:
        if is_real_video_url(src):
            real_urls.append({'url': src, 'content_length': 0, 'is_real_video': True})

    # Sort by content_length descending (largest video first)
    real_urls.sort(key=lambda x: x.get('content_length', 0), reverse=True)

    print(f'\n[3/3] Found {len(real_urls)} real video URL(s), {len(static_urls)} static asset(s)')

    if not real_urls:
        # Fallback: try static URLs that have significant size
        big_statics = [e for e in static_urls if e.get('content_length', 0) > 500000]
        if big_statics:
            print(f'  No real video URLs, but found {len(big_statics)} large static files')
            real_urls = big_statics

    if not real_urls:
        return {
            'success': False,
            'error': 'No video URL intercepted.',
            'page_title': page_title,
        }

    # Try each real video URL until one works
    for i, entry in enumerate(real_urls):
        vurl = entry['url']
        size_hint = entry.get('content_length', 0)
        print(f'\n  Trying URL {i+1}/{len(real_urls)} ({size_hint//1024}KB)...')
        result = download_video_direct(vurl, page_title or 'douyin_video')
        if result.get('success'):
            result['page_title'] = page_title
            result['description'] = page_description
            result['source_url'] = url
            result['video_source_url'] = vurl
            return result
        else:
            print(f'  Failed: {result.get("error")}')

    return {
        'success': False,
        'error': 'All intercepted video URLs failed to download.',
        'page_title': page_title,
    }


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else 'https://v.douyin.com/U5hpOFUnrXc/'

    print('=== Douyin Video Downloader (Playwright Intercept) ===\n')

    result = intercept_and_download(url)

    print('\n' + json.dumps(result, ensure_ascii=False, indent=2))

    if result.get('success'):
        print(f'\n=== Video downloaded successfully! ===')
        print(f'  Title: {result.get("page_title")}')
        print(f'  Path:  {result.get("video_path")}')
        print(f'  Size:  {result.get("size", 0) // 1024} KB')
    else:
        print(f'\n=== Download failed: {result.get("error")} ===')


if __name__ == '__main__':
    main()
