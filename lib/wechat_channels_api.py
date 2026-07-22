"""
WeChat Channels (微信视频号) video download module.

Two modes supported:

1. **Direct API mode** (no third-party dependency):
   - User provides a Yuanbao (元宝) cookie via environment variable
     WECHAT_CHANNELS_YUANBAO_COOKIE or function parameter.
   - The module directly calls:
     a) Tencent Yuanbao API to parse the share link → get export_id
     b) WeChat Channels API to get the video URL + metadata
   - This is the recommended mode — no dependency on any third-party service.

2. **Worker API mode** (fallback, out-of-box):
   - If no Yuanbao cookie is provided, falls back to the public Cloudflare
     Worker API (sph.litao.workers.dev) which does the same two-step process
     server-side using its own cookie.
   - Also supports a custom Worker URL via WECHAT_CHANNELS_WORKER_URL env var,
     so users can self-deploy their own Worker instance.

Reference: https://github.com/ltaoo/wx_channels_download
"""

import json
import os
import re
import time
import random
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

# Public Cloudflare Worker API (deployed by ltaoo/wx_channels_download)
# Can be overridden via WECHAT_CHANNELS_WORKER_URL env var
DEFAULT_WORKER_API_URL = "https://sph.litao.workers.dev/api/fetch_video_profile"

# Tencent Yuanbao API for parsing share links
YUANBAO_PARSE_URL = "https://yuanbao.tencent.com/api/weixin/get_parse_result"

# WeChat Channels API for getting feed info
CHANNELS_FEED_INFO_URL = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"

# Headers for downloading video from WeChat CDN
DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://channels.weixin.qq.com/",
    "Accept": "*/*",
}

# Headers for calling the Worker API
WORKER_API_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://sph.litao.workers.dev",
    "Referer": "https://sph.litao.workers.dev/",
}

# Headers for calling the Yuanbao API (mimicking a browser session)
YUANBAO_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "content-type": "application/json",
    "origin": "https://yuanbao.tencent.com",
    "referer": "https://yuanbao.tencent.com/chat/naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/148.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "t-userid": "b9575f6b0a8c4a55a08096904a5ef20a",
    "x-agentid": "naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
    "x-commit-tag": "72282a0d",
    "x-device-id": "1921b001708100d7fa31002b9646bd0cc15a3e2e1f",
    "x-hy106": "",
    "x-hy92": "e963067ffa31002b9646bd0c03000008b1951a",
    "x-hy93": "1921b001708100d7fa31002b9646bd0cc15a3e2e1f",
    "x-id": "b9575f6b0a8c4a55a08096904a5ef20a",
    "x-instance-id": "5",
    "x-language": "zh-CN",
    "x-os_version": "Mac OS(10.15.7)-Blink",
    "x-platform": "mac",
    "x-requested-with": "XMLHttpRequest",
    "x-source": "web",
    "x-web-third-source": "main",
    "x-webdriver": "0",
    "x-webversion": "2.69.0",
    "x-ybuitest": "0",
}

# Headers for calling the WeChat Channels API
CHANNELS_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "Origin": "https://channels.weixin.qq.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/148.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}


# ──────────────────────────────────────────────
# URL detection
# ──────────────────────────────────────────────

def is_wechat_channels(url: str) -> bool:
    """Check if URL is a WeChat Channels (视频号) link."""
    lower = url.lower()
    return any(pattern in lower for pattern in [
        "weixin.qq.com/sph/",
        "channels.weixin.qq.com/finder-preview",
        "channels.weixin.qq.com/web/pages/feed/",
    ])


# ──────────────────────────────────────────────
# Direct API mode — no third-party dependency
# ──────────────────────────────────────────────

def _generate_rid() -> str:
    """Generate a request ID (timestamp hex + random hex)."""
    timestamp_hex = format(int(time.time()), 'x')
    random_hex = ''.join(random.choice('0123456789abcdef') for _ in range(8))
    return f"{timestamp_hex}-{random_hex}"


def _parse_share_url_direct(share_url: str, cookie: str, timeout: int = 30) -> Optional[dict]:
    """
    Call the Tencent Yuanbao API directly to parse a WeChat Channels share link.

    This is Step 1 of the direct mode: sends the share URL to Yuanbao's
    get_parse_result API, which returns wx_export_id and playable_url.

    Args:
        share_url: WeChat Channels share URL
        cookie: Yuanbao web cookie (from yuanbao.tencent.com)
        timeout: Request timeout in seconds

    Returns:
        Parsed data dict with wx_export_id, playable_url, etc. or None on failure.
    """
    payload = json.dumps({
        "type": "video_channel_url",
        "url": share_url,
        "scene": 1,
    }).encode("utf-8")

    headers = dict(YUANBAO_HEADERS)
    headers["cookie"] = cookie

    req = urllib.request.Request(YUANBAO_PARSE_URL, data=payload, method="POST")
    for key, value in headers.items():
        req.add_header(key, value)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("data") and result["data"].get("wx_export_id"):
                return result["data"]
            else:
                print(f"[wechat_channels_api] Yuanbao API unexpected response: {result}")
                return None
    except Exception as e:
        print(f"[wechat_channels_api] _parse_share_url_direct error: {e}")
        return None


def _get_feed_info_direct(export_id: str, general_token: str, timeout: int = 30) -> Optional[dict]:
    """
    Call the WeChat Channels API directly to get video feed info.

    This is Step 2 of the direct mode: uses the export_id and token obtained
    from Step 1 to query the official WeChat Channels API for video URL and
    metadata.

    Args:
        export_id: The export ID (eid) from the parsed share URL
        general_token: The token from the parsed share URL
        timeout: Request timeout in seconds

    Returns:
        Full API response dict with feedInfo, authorInfo, etc. or None on failure.
    """
    rid = _generate_rid()
    payload = json.dumps({
        "baseReq": {"generalToken": general_token},
        "exportId": export_id,
    }).encode("utf-8")

    api_url = (
        f"{CHANNELS_FEED_INFO_URL}"
        f"?_rid={rid}"
        f"&_pageUrl=https:%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed"
    )

    referer = (
        "https://channels.weixin.qq.com/finder-preview/pages/feed"
        "?entry_card_type=48&comment_scene=39&appid=0"
        f"&token={urllib.parse.quote(general_token)}"
        f"&entry_scene=0&eid={urllib.parse.quote(export_id)}"
    )

    headers = dict(CHANNELS_HEADERS)
    headers["Referer"] = referer

    req = urllib.request.Request(api_url, data=payload, method="POST")
    for key, value in headers.items():
        req.add_header(key, value)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("errCode") == 0 and result.get("data"):
                return result["data"]
            else:
                print(f"[wechat_channels_api] Channels API error: {result}")
                return None
    except Exception as e:
        print(f"[wechat_channels_api] _get_feed_info_direct error: {e}")
        return None


def _fetch_video_profile_direct(share_url: str, cookie: str) -> Optional[dict]:
    """
    Full direct-mode pipeline: parse share URL → get feed info.

    Returns the data dict containing feedInfo and authorInfo,
    or None on failure.
    """
    # Step 1: Parse share URL via Yuanbao API
    parse_data = _parse_share_url_direct(share_url, cookie)
    if not parse_data:
        return None

    # Step 2: Extract token and export_id from playable_url
    general_token = ""
    export_id = ""
    try:
        playable_url = parse_data.get("playable_url", "")
        if playable_url:
            parsed = urllib.parse.urlparse(playable_url)
            params = urllib.parse.parse_qs(parsed.query)
            general_token = params.get("token", [""])[0]
            export_id = params.get("eid", [""])[0]
    except Exception:
        pass

    # Fall back to wx_export_id if eid not in URL params
    if not export_id:
        export_id = parse_data.get("wx_export_id", "")

    if not export_id:
        print("[wechat_channels_api] No export_id found in parsed data")
        return None

    # Step 3: Get feed info via WeChat Channels API
    feed_data = _get_feed_info_direct(export_id, general_token)
    if not feed_data:
        return None

    return feed_data


# ──────────────────────────────────────────────
# Worker API mode — fallback
# ──────────────────────────────────────────────

def _get_worker_api_url() -> str:
    """Get the Worker API URL from env var or use default."""
    return os.environ.get("WECHAT_CHANNELS_WORKER_URL", DEFAULT_WORKER_API_URL)


def is_custom_worker_configured() -> bool:
    """Return whether the user explicitly configured a Worker endpoint."""
    return bool(os.environ.get("WECHAT_CHANNELS_WORKER_URL", "").strip())


def is_public_worker_allowed() -> bool:
    """Return whether public Worker use is enabled (enabled by default)."""
    value = os.environ.get("WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER", "true")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_worker_allowed() -> bool:
    """Allow either an explicitly configured custom Worker or public opt-in."""
    return is_custom_worker_configured() or is_public_worker_allowed()


def _resolve_yuanbao_cookie(value: Optional[str]) -> str:
    """Prefer an explicit credential, then environment, then encrypted local storage."""
    if value and value.strip():
        return value.strip()
    env_cookie = os.environ.get("WECHAT_CHANNELS_YUANBAO_COOKIE", "").strip()
    if env_cookie:
        return env_cookie
    try:
        from .local_credentials import get_yuanbao_cookie
        return get_yuanbao_cookie()
    except Exception:
        return ""


def _parse_share_url_worker(share_url: str, timeout: int = 30) -> Optional[dict]:
    """
    Call the Cloudflare Worker API to parse a WeChat Channels share link.

    This is the fallback mode used when no Yuanbao cookie is provided.
    The Worker does the same two-step process server-side.
    """
    worker_url = _get_worker_api_url()
    payload = json.dumps({"url": share_url}).encode("utf-8")
    req = urllib.request.Request(worker_url, data=payload, method="POST")
    for key, value in WORKER_API_HEADERS.items():
        req.add_header(key, value)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("errCode") == 0 and result.get("data"):
                return result["data"]
            else:
                print(f"[wechat_channels_api] Worker API error: {result}")
                return None
    except Exception as e:
        print(f"[wechat_channels_api] _parse_share_url_worker error: {e}")
        return None


# ──────────────────────────────────────────────
# Unified parse function
# ──────────────────────────────────────────────

def parse_share_link(
    share_url: str,
    yuanbao_cookie: Optional[str] = None,
    timeout: int = 30,
) -> Optional[dict]:
    """
    Parse a WeChat Channels share link and return video metadata.

    Tries direct API mode first (if cookie available), then uses a Worker
    only when a custom endpoint is configured or public Worker use is enabled.

    Args:
        share_url: WeChat Channels share URL
        yuanbao_cookie: Cookie from yuanbao.tencent.com. If not provided,
            checks WECHAT_CHANNELS_YUANBAO_COOKIE env var. If still not
            found, a Worker requires explicit opt-in.
        timeout: Request timeout in seconds

    Returns:
        Data dict containing feedInfo and authorInfo, or None on failure.
    """
    # Resolve cookie from parameter or env var
    cookie = _resolve_yuanbao_cookie(yuanbao_cookie)

    if cookie:
        # Direct mode — no third-party dependency. Do not fall back to a
        # public service after the user chose their own local authorization.
        data = _fetch_video_profile_direct(share_url, cookie)
        if data:
            return data
        print("[wechat_channels_api] Local direct API mode failed.")
        return None

    if not is_worker_allowed():
        print(
            "[wechat_channels_api] Worker fallback disabled; configure a Yuanbao "
            "cookie, custom Worker URL, or explicit public-Worker opt-in."
        )
        return None

    return _parse_share_url_worker(share_url, timeout)


# ──────────────────────────────────────────────
# Download & info functions
# ──────────────────────────────────────────────

def download_video(
    share_url: str,
    output_dir: str,
    yuanbao_cookie: Optional[str] = None,
    timeout: int = 120,
) -> dict:
    """
    Fully automated WeChat Channels video download.

    1. Parse the share link (direct API or Worker fallback)
    2. Download the video from the CDN URL
    3. Return the result dict

    Args:
        share_url: WeChat Channels share URL (e.g. https://weixin.qq.com/sph/xxx)
        output_dir: Directory to save the video file
        yuanbao_cookie: Optional Yuanbao cookie for direct API mode.
            If not provided, checks WECHAT_CHANNELS_YUANBAO_COOKIE env var.
        timeout: Download timeout in seconds

    Returns:
        Dict with success status, video_path, metadata, etc.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Parse share link
    data = parse_share_link(share_url, yuanbao_cookie)
    if not data:
        cookie = _resolve_yuanbao_cookie(yuanbao_cookie)
        if cookie:
            error = "本机视频号授权无法解析此链接。请确认授权仍有效后重试。"
        elif not is_worker_allowed():
            error = (
                "Worker fallback is disabled. Configure "
                "WECHAT_CHANNELS_YUANBAO_COOKIE, WECHAT_CHANNELS_WORKER_URL, "
                "or WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER=true."
            )
        else:
            error = "公共视频号解析服务暂时无法解析此链接。请配置本机视频号授权后重试。"
        return {
            "success": False,
            "error": error,
            "output_dir": output_dir,
            "platform": "WeChat Channels",
            "url": share_url,
        }

    feed_info = data.get("feedInfo", {})
    author_info = data.get("authorInfo", {})

    # Extract video URL (prefer H.264 for compatibility)
    video_url = feed_info.get("videoUrl", "")
    if not video_url:
        h264 = feed_info.get("h264VideoInfo", {})
        video_url = h264.get("videoUrl", "") if h264 else ""

    if not video_url:
        h265 = feed_info.get("h265VideoInfo", {})
        video_url = h265.get("videoUrl", "") if h265 else ""

    if not video_url:
        return {
            "success": False,
            "error": "No video URL found in API response",
            "output_dir": output_dir,
            "platform": "WeChat Channels",
            "api_data": data,
        }

    # Extract metadata
    description = feed_info.get("description", "")
    nickname = author_info.get("nickname", "")
    title = description.split("\n")[0][:80] if description else (nickname or "WeChat Channels Video")
    # Clean title for filesystem
    safe_title = re.sub(r'[<>:"/\\|?*\n\r#]', " ", title).strip()[:80]
    if not safe_title:
        safe_title = "wechat_channels_video"

    # Determine which mode was used
    cookie = _resolve_yuanbao_cookie(yuanbao_cookie)
    download_method = "wechat_channels_direct" if cookie else "wechat_channels_worker"

    # Step 2: Download video
    output_path = os.path.join(output_dir, f"{safe_title}.mp4")

    req = urllib.request.Request(video_url)
    for key, value in DOWNLOAD_HEADERS.items():
        req.add_header(key, value)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            content_type = resp.headers.get("Content-Type", "")

            downloaded = 0
            with open(output_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

            # Verify it's a valid video file
            with open(output_path, "rb") as f:
                header = f.read(8)
            is_valid_mp4 = header[4:8] == b"ftyp" if len(header) >= 8 else False

            if not is_valid_mp4 and downloaded < 1024:
                # Probably an error response, not a video
                os.remove(output_path)
                return {
                    "success": False,
                    "error": f"Downloaded file is not a valid video (size={downloaded}, type={content_type})",
                    "output_dir": output_dir,
                    "platform": "WeChat Channels",
                }

            # Build metadata
            metadata = {
                "title": title,
                "description": description,
                "author": nickname,
                "author_avatar": author_info.get("headImgUrl", ""),
                "cover_url": feed_info.get("coverUrl", ""),
                "source_url": share_url,
                "extractor": "wechat_channels_api",
                "video_codec": "h264",
                "like_count": feed_info.get("likeCountFmt", ""),
                "comment_count": feed_info.get("commentCountFmt", ""),
                "forward_count": feed_info.get("forwardCountFmt", ""),
                "fav_count": feed_info.get("favCountFmt", ""),
                "location": feed_info.get("jumpInfo", {}).get("wording", ""),
                "create_time": feed_info.get("createtime", 0),
            }

            return {
                "success": True,
                "video_path": output_path,
                "size": downloaded,
                "subtitle_path": None,
                "subtitle_text": None,
                "has_subtitle": False,
                "metadata": metadata,
                "output_dir": output_dir,
                "download_method": download_method,
                "platform": "WeChat Channels",
            }

    except Exception as e:
        return {
            "success": False,
            "error": f"Download failed: {e}",
            "output_dir": output_dir,
            "platform": "WeChat Channels",
            "url": share_url,
        }


def get_video_info(
    share_url: str,
    yuanbao_cookie: Optional[str] = None,
) -> dict:
    """
    Get WeChat Channels video metadata without downloading.

    Args:
        share_url: WeChat Channels share URL
        yuanbao_cookie: Optional Yuanbao cookie for direct API mode

    Returns:
        Dict with success status and metadata.
    """
    data = parse_share_link(share_url, yuanbao_cookie)
    if not data:
        cookie = _resolve_yuanbao_cookie(yuanbao_cookie)
        if cookie:
            error = "本机视频号授权无法解析此链接。请确认授权仍有效后重试。"
        elif not is_worker_allowed():
            error = (
                "Worker fallback is disabled. Configure "
                "WECHAT_CHANNELS_YUANBAO_COOKIE, WECHAT_CHANNELS_WORKER_URL, "
                "or WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER=true."
            )
        else:
            error = "公共视频号解析服务暂时无法解析此链接。请配置本机视频号授权后重试。"
        return {
            "success": False,
            "error": error,
        }

    feed_info = data.get("feedInfo", {})
    author_info = data.get("authorInfo", {})
    description = feed_info.get("description", "")
    title = description.split("\n")[0][:80] if description else "WeChat Channels Video"

    cookie = _resolve_yuanbao_cookie(yuanbao_cookie)
    method = "wechat_channels_direct" if cookie else "wechat_channels_worker"

    return {
        "success": True,
        "metadata": {
            "title": title,
            "description": description,
            "author": author_info.get("nickname", ""),
            "author_avatar": author_info.get("headImgUrl", ""),
            "cover_url": feed_info.get("coverUrl", ""),
            "webpage_url": share_url,
            "extractor": method,
            "like_count": feed_info.get("likeCountFmt", ""),
            "comment_count": feed_info.get("commentCountFmt", ""),
            "forward_count": feed_info.get("forwardCountFmt", ""),
            "location": feed_info.get("jumpInfo", {}).get("wording", ""),
            "create_time": feed_info.get("createtime", 0),
            "has_video": bool(feed_info.get("videoUrl") or feed_info.get("h264VideoInfo")),
        },
        "available_subtitles": [],
        "available_auto_subs": [],
        "note": "WeChat Channels video info obtained via API. Use download_video to download.",
    }