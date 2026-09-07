from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from lib import downloader


class _FakeYDL:
    last_options = None

    def __init__(self, options):
        type(self).last_options = options
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def extract_info(self, _url, download=True):
        assert download
        path = self.options['outtmpl'].replace('%(id)s', 'audio').replace('%(ext)s', 'm4a')
        Path(path).write_bytes(b'audio')
        return {'id': 'audio', 'ext': 'm4a'}

    def prepare_filename(self, _info):
        return self.options['outtmpl'].replace('%(id)s', 'audio').replace('%(ext)s', 'm4a')


class AudioRetryTests(unittest.TestCase):
    def test_retry_audio_downloads_only_audio_and_merges_saved_video(self):
        fake_module = types.SimpleNamespace(YoutubeDL=_FakeYDL)
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / 'saved.mp4'
            video.write_bytes(b'video')
            merge_calls = []

            def merge(video_path, audio_path, _ffmpeg):
                merge_calls.append((video_path, audio_path))
                video.write_bytes(b'video+audio')
                return True

            with patch.dict('sys.modules', {'yt_dlp': fake_module}), \
                 patch('lib.downloader.find_ffmpeg', return_value='ffmpeg'), \
                 patch('lib.downloader._audio_track_state', return_value='present'), \
                 patch('lib.playwright_downloader._merge_audio', side_effect=merge):
                result = downloader.retry_audio('https://example.com/watch/1', str(video))

            self.assertTrue(result['success'])
            self.assertEqual(result['download_method'], 'audio_retry')
            self.assertEqual(len(merge_calls), 1)
            self.assertIn('bestaudio', _FakeYDL.last_options['format'])
            self.assertNotIn('bestvideo', _FakeYDL.last_options['format'])
            self.assertFalse(any(Path(directory).glob('.audio-retry-*')))

    def test_retry_audio_keeps_saved_video_when_audio_download_fails(self):
        class FailingYDL(_FakeYDL):
            def extract_info(self, _url, download=True):
                raise RuntimeError('HTTP Error 503')

        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / 'saved.mp4'
            video.write_bytes(b'original')
            with patch.dict('sys.modules', {'yt_dlp': types.SimpleNamespace(YoutubeDL=FailingYDL)}), \
                 patch('lib.downloader.find_ffmpeg', return_value='ffmpeg'):
                result = downloader.retry_audio('https://example.com/watch/1', str(video))

            self.assertFalse(result['success'])
            self.assertEqual(video.read_bytes(), b'original')
            self.assertEqual(result['failed_stage'], '音频下载')


if __name__ == '__main__':
    unittest.main()
