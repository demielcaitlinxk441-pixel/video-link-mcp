#!/usr/bin/env python
"""
Video Link Analyzer - MCP Server
=================================

Standalone MCP (Model Context Protocol) server that provides:
  1. Smart link type detection (video / article / design page)
  2. Video download with audio + subtitles (via yt-dlp)
  3. Speech-to-text transcription fallback (via Whisper, optional)
  4. One-stop video analysis pipeline
  5. WeChat Channels (视频号) download via direct API calls (recommended)
     or Cloudflare Worker API (fallback)

Connect from WorkBuddy, Codex, or any MCP-compatible client.

Usage:
    python server.py

MCP tools exposed:
    - detect_link_type      : Identify URL type
    - get_video_info        : Fetch video metadata without downloading
    - download_video        : Download video + audio + subtitles
    - extract_transcript    : Whisper-based transcription
    - analyze_video         : Full pipeline (download + subtitle/STT)
"""

import os
import sys
import json

# Ensure the lib directory is importable regardless of CWD
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from mcp.server.fastmcp import FastMCP

from lib.detector import detect_link_type as _detect_link_type
from lib.downloader import download_video as _download_video
from lib.downloader import get_video_info as _get_video_info
from lib.transcriber import transcribe_audio as _transcribe_audio

mcp = FastMCP('video-link-analyzer')


def _build_cookie_kwargs(
    cookies_from_browser: str = '',
    cookies_file: str = '',
    proxy: str = '',
    yuanbao_cookie: str = '',
) -> dict:
    """Build kwargs dict for downloader functions from optional string args."""
    kwargs = {}
    if cookies_from_browser and cookies_from_browser.strip():
        kwargs['cookies_from_browser'] = cookies_from_browser.strip()
    if cookies_file and cookies_file.strip():
        kwargs['cookies_file'] = cookies_file.strip()
    if proxy and proxy.strip():
        kwargs['proxy'] = proxy.strip()
    if yuanbao_cookie and yuanbao_cookie.strip():
        kwargs['yuanbao_cookie'] = yuanbao_cookie.strip()
    return kwargs


# ──────────────────────────────────────────────
# Tool 1: Link Type Detection
# ──────────────────────────────────────────────

@mcp.tool()
def detect_link_type(url: str) -> str:
    """
    Detect the type of a URL: video, article, or design page.

    Uses URL pattern matching for known platforms (YouTube, Bilibili,
    Vimeo, Douyin, TikTok, etc.) and falls back to page metadata
    analysis for unknown URLs.

    Args:
        url: The URL to analyze.

    Returns:
        JSON string with fields:
          - type: "video" | "article" | "design_page" | "unknown"
          - platform: platform name (e.g. "YouTube") or null
          - details: human-readable description
          - confidence: 0.0 to 1.0
    """
    result = _detect_link_type(url)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# Tool 2: Video Info (no download)
# ──────────────────────────────────────────────

@mcp.tool()
def get_video_info(
    url: str,
    cookies_from_browser: str = '',
    cookies_file: str = '',
    proxy: str = '',
    yuanbao_cookie: str = '',
) -> str:
    """
    Fetch video metadata without downloading the file.

    Quickly retrieves title, duration, description, uploader, view count,
    and available subtitle languages.

    Args:
        url: Video URL.
        cookies_from_browser: Browser to read cookies from automatically
            (e.g. "chrome", "edge", "firefox"). Useful for Douyin/TikTok.
        cookies_file: Path to a Netscape-format cookies.txt file.
        proxy: Proxy URL, e.g. "http://127.0.0.1:7890".
        yuanbao_cookie: Yuanbao web cookie for WeChat Channels direct API
            mode (eliminates third-party dependency). Get it from
            yuanbao.tencent.com after logging in. If not provided, checks
            WECHAT_CHANNELS_YUANBAO_COOKIE env var, then falls back to
            the public Worker API.

    Returns:
        JSON string with video metadata and available subtitle info.
    """
    kwargs = _build_cookie_kwargs(cookies_from_browser, cookies_file, proxy, yuanbao_cookie)
    result = _get_video_info(url, **kwargs)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# Tool 3: Download Video
# ──────────────────────────────────────────────

@mcp.tool()
def download_video(
    url: str,
    output_dir: str = '',
    cookies_from_browser: str = '',
    cookies_file: str = '',
    proxy: str = '',
    yuanbao_cookie: str = '',
) -> str:
    """
    Download a video with audio and subtitles.

    Uses yt-dlp to download the best available video + audio (merged to
    MP4) and attempts to fetch subtitles in the preferred language order:
    zh-Hans, zh, en. Prefers manual subtitles, falls back to auto-generated.

    Douyin users: pass cookies_from_browser="chrome" (or edge/firefox) if
    you see "Fresh cookies needed" errors.

    WeChat Channels (视频号): Two modes —
      1. Direct API (recommended): pass yuanbao_cookie or set
         WECHAT_CHANNELS_YUANBAO_COOKIE env var. Calls Tencent APIs
         directly, no third-party dependency.
      2. Worker API (fallback): if no cookie is provided, uses the public
         Cloudflare Worker at sph.litao.workers.dev. Also supports a
         custom Worker via WECHAT_CHANNELS_WORKER_URL env var.

    Args:
        url: Video URL.
        output_dir: Directory to save files. Defaults to system temp dir.
        cookies_from_browser: Browser to read cookies from automatically
            (e.g. "chrome", "edge", "firefox"). Useful for Douyin/TikTok.
        cookies_file: Path to a Netscape-format cookies.txt file.
        proxy: Proxy URL, e.g. "http://127.0.0.1:7890".
        yuanbao_cookie: Yuanbao web cookie for WeChat Channels direct API
            mode. Get it from yuanbao.tencent.com after logging in.

    Returns:
        JSON string with:
          - video_path: path to downloaded video
          - subtitle_path: path to subtitle file (or null)
          - subtitle_text: parsed subtitle plain text (or null)
          - metadata: video title, duration, description, etc.
          - download_method: "yt-dlp" | "playwright_intercept" |
            "wechat_channels_direct" | "wechat_channels_worker"
    """
    kwargs = _build_cookie_kwargs(cookies_from_browser, cookies_file, proxy, yuanbao_cookie)
    result = _download_video(url, output_dir or None, **kwargs)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# Tool 4: Extract Transcript (Whisper STT)
# ──────────────────────────────────────────────

@mcp.tool()
def extract_transcript(
    url: str = '',
    video_path: str = '',
    language: str = 'zh',
    cookies_from_browser: str = '',
    cookies_file: str = '',
    proxy: str = '',
    yuanbao_cookie: str = '',
) -> str:
    """
    Extract a text transcript from a video using Whisper speech-to-text.

    Use this when a video has no subtitles. Requires faster-whisper or
    openai-whisper to be installed (optional dependency).

    Provide either a URL (the video will be downloaded first) or a local
    video file path.

    Args:
        url: Video URL to download and transcribe (alternative to video_path).
        video_path: Local video file path (alternative to url).
        language: Language code for transcription (default: "zh").
        cookies_from_browser: Browser to read cookies from automatically.
        cookies_file: Path to a Netscape-format cookies.txt file.
        proxy: Proxy URL, e.g. "http://127.0.0.1:7890".
        yuanbao_cookie: Yuanbao web cookie for WeChat Channels direct API.

    Returns:
        JSON string with transcript text and time-coded segments.
    """
    kwargs = _build_cookie_kwargs(cookies_from_browser, cookies_file, proxy, yuanbao_cookie)

    # Download first if URL is provided
    if url and not video_path:
        dl = _download_video(url, None, **kwargs)
        if dl.get('success'):
            video_path = dl.get('video_path', '')
        else:
            return json.dumps(dl, ensure_ascii=False, indent=2)

    if not video_path or not os.path.exists(video_path):
        return json.dumps(
            {'success': False,
             'error': 'No video file available for transcription.'},
            ensure_ascii=False, indent=2,
        )

    result = _transcribe_audio(video_path, language)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# Tool 5: Full Analysis Pipeline
# ──────────────────────────────────────────────

@mcp.tool()
def analyze_video(
    url: str,
    output_dir: str = '',
    cookies_from_browser: str = '',
    cookies_file: str = '',
    proxy: str = '',
    yuanbao_cookie: str = '',
) -> str:
    """
    Full video analysis pipeline: download -> subtitles -> STT fallback.

    Automatically performs these steps:
      1. Downloads the video (best quality, merged MP4) with audio.
      2. Attempts to fetch subtitles (zh-Hans, zh, en).
      3. If subtitles are found, returns their text.
      4. If no subtitles, attempts Whisper speech-to-text (if installed).
      5. Returns all data for downstream AI analysis.

    Douyin users: pass cookies_from_browser="chrome" (or edge/firefox) if
    you see "Fresh cookies needed" errors.

    WeChat Channels: pass yuanbao_cookie or set WECHAT_CHANNELS_YUANBAO_COOKIE
    env var for direct API mode (no third-party dependency).

    Args:
        url: Video URL.
        output_dir: Directory to save files (default: system temp dir).
        cookies_from_browser: Browser to read cookies from automatically
            (e.g. "chrome", "edge", "firefox"). Useful for Douyin/TikTok.
        cookies_file: Path to a Netscape-format cookies.txt file.
        proxy: Proxy URL, e.g. "http://127.0.0.1:7890".
        yuanbao_cookie: Yuanbao web cookie for WeChat Channels direct API.

    Returns:
        JSON string with video_path, transcript, transcript_source
        ("subtitle" | "whisper" | "none"), metadata, and file paths.
    """
    kwargs = _build_cookie_kwargs(cookies_from_browser, cookies_file, proxy, yuanbao_cookie)

    # Step 1: Download
    dl = _download_video(url, output_dir or None, **kwargs)
    if not dl.get('success'):
        return json.dumps(dl, ensure_ascii=False, indent=2)

    # Step 2: Check subtitles
    if dl.get('has_subtitle') and dl.get('subtitle_text'):
        dl['transcript_source'] = 'subtitle'
        dl['transcript'] = dl['subtitle_text']
        return json.dumps(dl, ensure_ascii=False, indent=2)

    # Step 3: Try Whisper transcription
    video_path = dl.get('video_path', '')
    if video_path and os.path.exists(video_path):
        stt = _transcribe_audio(video_path, 'zh')
        if stt.get('success'):
            dl['transcript_source'] = 'whisper'
            dl['transcript'] = stt.get('transcript', '')
            dl['transcript_segments'] = stt.get('segments', [])
            dl['transcript_engine'] = stt.get('engine', '')
        else:
            dl['transcript_source'] = 'none'
            dl['transcript'] = ''
            dl['transcript_error'] = stt.get('error', 'Unknown error')
    else:
        dl['transcript_source'] = 'none'
        dl['transcript'] = ''

    return json.dumps(dl, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == '__main__':
    mcp.run()
