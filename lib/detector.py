"""
Link type detection module.
Identifies whether a URL points to a video, article, or design page.
Uses URL pattern matching + page metadata analysis.
"""

import re
import urllib.request
import urllib.error
from typing import Optional


VIDEO_PLATFORMS = {
    'youtube': {
        'patterns': [r'youtube\.com/watch', r'youtu\.be/', r'youtube\.com/shorts/', r'youtube\.com/embed/'],
        'name': 'YouTube',
    },
    'bilibili': {
        'patterns': [r'bilibili\.com/video', r'b23\.tv/'],
        'name': 'Bilibili',
    },
    'vimeo': {
        'patterns': [r'vimeo\.com/\d+', r'player\.vimeo\.com/video/'],
        'name': 'Vimeo',
    },
    'douyin': {
        'patterns': [r'douyin\.com/video', r'iesdouyin\.com/share', r'v\.douyin\.com'],
        'name': 'Douyin',
    },
    'tiktok': {
        'patterns': [r'tiktok\.com/.+/video/', r'vm\.tiktok\.com'],
        'name': 'TikTok',
    },
    'twitter': {
        'patterns': [r'twitter\.com/.+/status/', r'x\.com/.+/status/'],
        'name': 'Twitter/X',
    },
    'instagram': {
        'patterns': [r'instagram\.com/(p|reel|reels)/'],
        'name': 'Instagram',
    },
    'weibo': {
        'patterns': [r'weibo\.com/\d+', r'm\.weibo\.cn/status/'],
        'name': 'Weibo',
    },
    'tencent': {
        'patterns': [r'v\.qq\.com/x/(cover|page)/'],
        'name': 'Tencent Video',
    },
    'youku': {
        'patterns': [r'youku\.com/v_show/', r'v\.youku\.com'],
        'name': 'Youku',
    },
    'iqiyi': {
        'patterns': [r'iqiyi\.com/v_', r'iqiyi\.com/w_'],
        'name': 'iQiyi',
    },
    'zhihu': {
        'patterns': [r'zhihu\.com/zvideo/', r'video\.zhihu\.com'],
        'name': 'Zhihu Video',
    },
    'xiaohongshu': {
        'patterns': [
            r'xiaohongshu\.com/explore/',
            r'xiaohongshu\.com/note/',
            r'xiaohongshu\.com/discovery/item/',
            r'xhslink\.com',
        ],
        'name': 'Xiaohongshu',
    },
    'douyu': {
        'patterns': [r'douyu\.com'],
        'name': 'Douyu',
    },
    'huya': {
        'patterns': [r'huya\.com'],
        'name': 'Huya',
    },
    'wechat_channels': {
        'patterns': [
            r'weixin\.qq\.com/sph/',
            r'channels\.weixin\.qq\.com/finder-preview',
            r'channels\.weixin\.qq\.com/web/pages/feed/',
        ],
        'name': 'WeChat Channels',
    },
}

VIDEO_FILE_EXTENSIONS = r'\.(mp4|avi|mov|mkv|webm|flv|wmv|m4v|mpg|mpeg|3gp)(\?|$)'


def detect_video_platform(url: str) -> Optional[dict]:
    """Check if URL matches any known video platform."""
    for key, info in VIDEO_PLATFORMS.items():
        for pattern in info['patterns']:
            if re.search(pattern, url, re.IGNORECASE):
                return {
                    'platform_key': key,
                    'platform_name': info['name'],
                }
    return None


def fetch_page_metadata(url: str, timeout: int = 15) -> dict:
    """Fetch page HTML metadata to determine content type."""
    default = {
        'error': '', 'content_type': '', 'has_video_tag': False,
        'has_og_video': False, 'has_video_src': False, 'og_type': '',
        'title': '', 'text_density': 0, 'has_article_tag': False,
        'has_large_text': False, 'div_count': 0, 'has_canvas': False,
    }
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get('Content-Type', '')
            html = response.read(100_000).decode('utf-8', errors='ignore')

            has_video_tag = bool(re.search(r'<video[^>]*>', html, re.IGNORECASE))
            has_og_video = bool(re.search(r'property=["\']og:video', html, re.IGNORECASE))
            has_video_src = bool(re.search(r'<source[^>]*type=["\']video/', html, re.IGNORECASE))

            og_type_match = re.search(
                r'property=["\']og:type["\']\s+content=["\']([^"\']*)["\']',
                html, re.IGNORECASE,
            )
            og_type = og_type_match.group(1).lower() if og_type_match else ''

            title_match = re.search(r'<title[^>]*>([^<]*)</title>', html, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else ''

            text_only = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text_only = re.sub(r'<style[^>]*>.*?</style>', '', text_only, flags=re.DOTALL | re.IGNORECASE)
            text_only = re.sub(r'<[^>]+>', '', text_only).strip()
            text_density = len(text_only)

            has_article_tag = bool(re.search(r'<article[^>]*>', html, re.IGNORECASE))
            has_large_text = text_density > 3000
            div_count = len(re.findall(r'<div[^>]*>', html, re.IGNORECASE))
            has_canvas = bool(re.search(r'<canvas|<svg|webgl|three\.js', html, re.IGNORECASE))

            return {
                'error': '', 'content_type': content_type,
                'has_video_tag': has_video_tag, 'has_og_video': has_og_video,
                'has_video_src': has_video_src, 'og_type': og_type,
                'title': title, 'text_density': text_density,
                'has_article_tag': has_article_tag, 'has_large_text': has_large_text,
                'div_count': div_count, 'has_canvas': has_canvas,
            }
    except urllib.error.HTTPError as e:
        default['error'] = f'HTTP {e.code}: {e.reason}'
        return default
    except Exception as e:
        default['error'] = str(e)
        return default


def detect_link_type(url: str) -> dict:
    """
    Detect the type of a URL.

    Returns a dict with:
        - type: 'video' | 'article' | 'design_page' | 'unknown'
        - platform: platform name (if video)
        - details: human-readable description
        - confidence: 0.0 to 1.0
    """
    # Step 1: Known video platforms (highest confidence)
    platform_info = detect_video_platform(url)
    if platform_info:
        return {
            'type': 'video',
            'platform': platform_info['platform_name'],
            'platform_key': platform_info['platform_key'],
            'details': f'URL matches known video platform: {platform_info["platform_name"]}',
            'confidence': 0.95,
            'url': url,
        }

    # Step 2: Direct video file URL
    if re.search(VIDEO_FILE_EXTENSIONS, url, re.IGNORECASE):
        return {
            'type': 'video',
            'platform': 'direct_link',
            'platform_key': 'direct',
            'details': 'URL points directly to a video file',
            'confidence': 0.90,
            'url': url,
        }

    # Step 3: Fetch and analyze page
    page = fetch_page_metadata(url)

    if page.get('error'):
        return {
            'type': 'unknown',
            'platform': None,
            'platform_key': None,
            'details': f'Could not fetch page: {page["error"]}',
            'confidence': 0.10,
            'url': url,
        }

    # Video indicators in page HTML
    if page['has_video_tag'] or page['has_og_video'] or page['has_video_src']:
        return {
            'type': 'video',
            'platform': 'web_video',
            'platform_key': 'web',
            'details': f'Page contains embedded video (title: {page["title"]})',
            'confidence': 0.85,
            'url': url,
            'page_title': page['title'],
        }

    # Article indicators
    if page['og_type'] == 'article' or page['has_article_tag'] or page['has_large_text']:
        return {
            'type': 'article',
            'platform': None,
            'platform_key': None,
            'details': f'Page appears to be an article (title: {page["title"]})',
            'confidence': 0.80,
            'url': url,
            'page_title': page['title'],
            'text_density': page['text_density'],
        }

    # Design page indicators: many divs, low text, visual elements
    if page['div_count'] > 20 and page['text_density'] < 2000:
        return {
            'type': 'design_page',
            'platform': None,
            'platform_key': None,
            'details': f'Page appears to be a design/visual page (title: {page["title"]})',
            'confidence': 0.65,
            'url': url,
            'page_title': page['title'],
            'div_count': page['div_count'],
        }

    # Fallback: text-heavy => article, otherwise => design page
    if page['text_density'] > 1500:
        return {
            'type': 'article',
            'platform': None,
            'platform_key': None,
            'details': f'Page has substantial text content (title: {page["title"]})',
            'confidence': 0.60,
            'url': url,
            'page_title': page['title'],
            'text_density': page['text_density'],
        }

    return {
        'type': 'design_page',
        'platform': None,
        'platform_key': None,
        'details': f'Page appears to be a visual/design page (title: {page["title"]})',
        'confidence': 0.55,
        'url': url,
        'page_title': page['title'],
    }
