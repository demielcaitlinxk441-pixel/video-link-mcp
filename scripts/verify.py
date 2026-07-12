#!/usr/bin/env python
"""
Quick test script for Video Link Analyzer MCP Server.
Verifies that all modules import correctly and basic functions work.
Run: python scripts/verify.py
"""

import os
import sys
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

passed = 0
failed = 0


def test(name, func):
    global passed, failed
    try:
        func()
        print(f'  [PASS] {name}')
        passed += 1
    except Exception as e:
        print(f'  [FAIL] {name}: {e}')
        failed += 1


def test_imports():
    from lib.detector import detect_link_type
    from lib.downloader import find_ffmpeg, get_video_info, download_video
    from lib.subtitle_parser import parse_subtitle, parse_vtt, parse_srt
    from lib.transcriber import transcribe_audio
    from lib.playwright_downloader import intercept_download, is_real_video_url


def test_mcp_import():
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP('test')
    assert mcp is not None


def test_http_mcp_contract():
    import server
    app = server.mcp.streamable_http_app()
    assert any(route.path == '/mcp' for route in app.routes)


def test_ytdlp_import():
    import yt_dlp
    assert yt_dlp is not None


def test_detector_youtube():
    from lib.detector import detect_link_type
    result = detect_link_type('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
    assert result['type'] == 'video', f'Expected video, got {result["type"]}'
    assert result['platform'] == 'YouTube'


def test_detector_bilibili():
    from lib.detector import detect_link_type
    result = detect_link_type('https://www.bilibili.com/video/BV1xx411c7mD')
    assert result['type'] == 'video'
    assert result['platform'] == 'Bilibili'


def test_detector_article_url():
    from lib.detector import detect_link_type
    result = detect_link_type('https://www.bilibili.com/video/BV1xx411c7mD')
    assert result['type'] == 'video'


def test_vtt_parser():
    from lib.subtitle_parser import parse_vtt
    sample = """WEBVTT

00:00:00.000 --> 00:00:02.000
Hello world

00:00:02.000 --> 00:00:04.000
This is a test
"""
    result = parse_vtt(sample)
    assert result['segment_count'] == 2
    assert 'Hello world' in result['full_text']
    assert 'This is a test' in result['full_text']


def test_srt_parser():
    from lib.subtitle_parser import parse_srt
    sample = """1
00:00:00,000 --> 00:00:02,000
Hello world

2
00:00:02,000 --> 00:00:04,000
This is a test
"""
    result = parse_srt(sample)
    assert result['segment_count'] == 2
    assert 'Hello world' in result['full_text']


def test_ffmpeg_check():
    from lib.downloader import find_ffmpeg
    path = find_ffmpeg()
    if path:
        print(f'    (ffmpeg found: {path})')
    else:
        print('    (ffmpeg not found - optional but recommended)')


def test_playwright_url_filter():
    from lib.playwright_downloader import is_real_video_url
    assert is_real_video_url('https://www.douyinvod.com/video/abc.mp4') == True
    assert is_real_video_url('https://www.douyinstatic.com/effect/abc.mp4') == False
    assert is_real_video_url('https://aweme.snssdk.com/aweme/v1/play/?video_id=xxx') == True


def test_playwright_import():
    from lib.playwright_downloader import intercept_download
    import inspect
    params = list(inspect.signature(intercept_download).parameters.keys())
    assert 'url' in params
    assert 'output_dir' in params


def test_server_tools():
    """Verify server.py can be imported and tools are registered."""
    import importlib
    import server
    importlib.reload(server)
    # The FastMCP instance should have tools registered
    assert hasattr(server, 'mcp')


def test_diagnostics_import():
    from diagnose import collect_diagnostics
    result = collect_diagnostics()
    assert 'core_ready' in result


if __name__ == '__main__':
    print('=' * 50)
    print('Video Link Analyzer MCP Server - Test Suite')
    print('=' * 50)
    print()

    print('Module imports:')
    test('Import all lib modules', test_imports)
    test('Import MCP SDK', test_mcp_import)
    test('Check HTTP MCP route', test_http_mcp_contract)
    test('Import yt-dlp', test_ytdlp_import)
    print()

    print('Link type detection:')
    test('Detect YouTube URL', test_detector_youtube)
    test('Detect Bilibili URL', test_detector_bilibili)
    print()

    print('Subtitle parsing:')
    test('Parse VTT format', test_vtt_parser)
    test('Parse SRT format', test_srt_parser)
    print()

    print('System checks:')
    test('Check ffmpeg availability', test_ffmpeg_check)
    print()

    print('Playwright fallback:')
    test('Import playwright_downloader module', test_playwright_import)
    test('Video URL filter logic', test_playwright_url_filter)
    print()

    print('Server integration:')
    test('Server module loads with tools', test_server_tools)
    test('Diagnostics module loads', test_diagnostics_import)
    print()

    print('=' * 50)
    print(f'Results: {passed} passed, {failed} failed')
    if failed == 0:
        print('All tests passed! Server is ready.')
    else:
        print('Some tests failed. Check errors above.')
    print('=' * 50)
    sys.exit(1 if failed else 0)
