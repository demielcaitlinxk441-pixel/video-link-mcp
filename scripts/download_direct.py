#!/usr/bin/env python
"""
Standalone command-line video downloader using the project's downloader module.

Usage:
    python scripts/download_direct.py <URL> [chrome|edge|firefox] [output_dir]

Examples:
    python scripts/download_direct.py https://www.douyin.com/video/123456789 chrome
    python scripts/download_direct.py https://www.youtube.com/watch?v=xxx edge ./videos
    python scripts/download_direct.py https://www.douyin.com/video/123456789 "" ./videos --cookies-file=cookies.txt
"""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.downloader import download_video


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    url = sys.argv[1]
    browser = sys.argv[2] if len(sys.argv) > 2 else ''
    output_dir = sys.argv[3] if len(sys.argv) > 3 else ''

    cookies_file = None
    proxy = None

    # Parse optional flags like --cookies-file=... --proxy=...
    for arg in sys.argv[4:]:
        if arg.startswith('--cookies-file='):
            cookies_file = arg.split('=', 1)[1]
        elif arg.startswith('--proxy='):
            proxy = arg.split('=', 1)[1]

    kwargs = {}
    if browser:
        kwargs['cookies_from_browser'] = browser
    if cookies_file:
        kwargs['cookies_file'] = cookies_file
    if proxy:
        kwargs['proxy'] = proxy

    result = download_video(url, output_dir or None, **kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result.get('success'):
        sys.exit(1)


if __name__ == '__main__':
    main()
