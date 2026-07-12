#!/usr/bin/env python
"""Offline environment diagnostics for Video Link Analyzer MCP Server."""

import argparse
import importlib.util
import json
import os
import shutil
import sys


REQUIRED_PACKAGES = ('mcp', 'yt_dlp', 'playwright')


def _chromium_is_installed() -> bool:
    """Check Playwright's local Chromium executable without network access."""
    if importlib.util.find_spec('playwright') is None:
        return False

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            return os.path.exists(playwright.chromium.executable_path)
    except Exception:
        return False


def collect_diagnostics() -> dict:
    """Return machine-readable status for core and optional capabilities."""
    dependencies = {
        package: importlib.util.find_spec(package) is not None
        for package in REQUIRED_PACKAGES
    }
    supported_python = (3, 10) <= sys.version_info[:2] <= (3, 13)

    return {
        'python': sys.version.split()[0],
        'supported_python': supported_python,
        'core_dependencies': dependencies,
        'ffmpeg': shutil.which('ffmpeg') is not None,
        'playwright_browser': _chromium_is_installed(),
        'speech_to_text': importlib.util.find_spec('faster_whisper') is not None,
        'core_ready': supported_python and all(dependencies.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Check local Video Link Analyzer dependencies.')
    parser.add_argument('--json', action='store_true', help='print the result as JSON')
    args = parser.parse_args()
    result = collect_diagnostics()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Python: {result['python']} ({'supported' if result['supported_python'] else 'unsupported'})")
        print(f"Core dependencies: {result['core_dependencies']}")
        print(f"ffmpeg: {'found' if result['ffmpeg'] else 'not found'}")
        print(f"Playwright Chromium: {'found' if result['playwright_browser'] else 'not found'}")
        print(f"Speech-to-text: {'installed' if result['speech_to_text'] else 'not installed'}")
        print(f"Core ready: {'yes' if result['core_ready'] else 'no'}")

    return 0 if result['core_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
