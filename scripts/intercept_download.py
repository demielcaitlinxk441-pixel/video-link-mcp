#!/usr/bin/env python
"""Run the project's Playwright fallback downloader from the command line."""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.playwright_downloader import intercept_download


def main() -> int:
    parser = argparse.ArgumentParser(
        description='使用 Playwright 拦截并下载视频。'
    )
    parser.add_argument('url', help='视频页面链接')
    parser.add_argument(
        '--output-dir',
        help='保存目录；未填写时使用系统临时目录。',
    )
    args = parser.parse_args()

    result = intercept_download(args.url, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    raise SystemExit(main())
