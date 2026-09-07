from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from lib import downloader


class SubtitleRetryTests(unittest.TestCase):
    def test_subtitle_only_retry_never_requests_media(self):
        class SubtitleYDL:
            options = None

            def __init__(self, options):
                type(self).options = options

            def __enter__(self): return self
            def __exit__(self, *_args): return False

            def extract_info(self, _url, download=True):
                base = self.options['outtmpl'].replace('%(title).80s', 'title').replace('%(id)s', 'vid').replace('%(ext)s', 'mp4')
                Path(base).with_suffix('.zh.vtt').write_text(
                    'WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n字幕内容\n', encoding='utf-8'
                )
                return {'id': 'vid', 'title': 'title', 'ext': 'mp4'}

            def prepare_filename(self, _info):
                return self.options['outtmpl'].replace('%(title).80s', 'title').replace('%(id)s', 'vid').replace('%(ext)s', 'mp4')

        with tempfile.TemporaryDirectory() as directory, \
             patch.dict('sys.modules', {'yt_dlp': types.SimpleNamespace(YoutubeDL=SubtitleYDL)}), \
             patch('lib.downloader.find_ffmpeg', return_value=None):
            result = downloader.retry_subtitle('https://example.com/video', directory)

        self.assertTrue(result['success'])
        self.assertEqual(result['subtitle_text'], '字幕内容')
        self.assertTrue(SubtitleYDL.options['skip_download'])
        self.assertNotIn('format', SubtitleYDL.options)

    def test_subtitle_failure_does_not_turn_saved_media_into_failure(self):
        class MediaYDL:
            def __init__(self, options): self.options = options
            def __enter__(self): return self
            def __exit__(self, *_args): return False

            def extract_info(self, _url, download=True):
                path = self.prepare_filename({'id': 'vid', 'title': 'title', 'ext': 'mp4'})
                Path(path).write_bytes(b'video')
                return {'id': 'vid', 'title': 'title', 'ext': 'mp4'}

            def prepare_filename(self, _info):
                return self.options['outtmpl'].replace('%(title).80s', 'title').replace('%(id)s', 'vid').replace('%(ext)s', 'mp4')

        subtitle_failure = {
            'success': False, 'subtitle_status': 'failed',
            'failure': {'failed_stage': '字幕下载', 'reason': 'HTTP 429'},
        }
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict('sys.modules', {'yt_dlp': types.SimpleNamespace(YoutubeDL=MediaYDL)}), \
             patch('lib.downloader.find_ffmpeg', return_value=None), \
             patch('lib.downloader._retry_subtitle_impl', return_value=subtitle_failure), \
             patch('lib.downloader._ensure_compatible_video', side_effect=lambda result, *_: result):
            result = downloader.download_video('https://example.com/video', directory)

        self.assertTrue(result['success'])
        self.assertEqual(result['subtitle_status'], 'failed')
        self.assertEqual(result['subtitle_failure']['failed_stage'], '字幕下载')
        self.assertTrue(result['video_path'].endswith('.mp4'))


if __name__ == '__main__':
    unittest.main()
