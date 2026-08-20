import io
import threading
import tempfile
import unittest
from unittest.mock import patch

from lib import downloader
from lib.playwright_downloader import (
    _download_file, _is_audio_response, _is_kuaishou_url,
    _media_candidates_ready, _merge_audio, is_real_video_url,
)


class PlaywrightFallbackTests(unittest.TestCase):
    def test_intercept_runs_in_a_worker_thread(self):
        caller_thread = threading.get_ident()

        def fake_intercept(url, output_dir):
            return {
                'success': True,
                'url': url,
                'output_dir': output_dir,
                'thread_id': threading.get_ident(),
            }

        with patch(
            'lib.playwright_downloader.intercept_download',
            side_effect=fake_intercept,
        ):
            result = downloader._run_playwright_intercept(
                'https://v.douyin.com/example/', 'C:/downloads'
            )

        self.assertTrue(result['success'])
        self.assertNotEqual(result['thread_id'], caller_thread)

    def test_kuaishou_urls_and_cdn_are_detected(self):
        self.assertTrue(downloader._is_kuaishou('https://www.kuaishou.com/f/share-token'))
        self.assertTrue(downloader._is_kuaishou('https://m.gifshow.com/fw/photo/example'))
        legacy_url = 'https://v.m.chenzhongtech.com/fw/photo/3xgspcsnjj4dfv9?cc=share_wxms'
        self.assertTrue(downloader._is_kuaishou(legacy_url))
        self.assertTrue(_is_kuaishou_url(legacy_url))
        self.assertFalse(downloader._is_kuaishou('https://www.bilibili.com/video/BV1xx'))
        self.assertTrue(is_real_video_url('https://tx2.a.kwimgs.com/upic/2026/07/16/example.mp4'))
        self.assertTrue(is_real_video_url('https://v1.kwaicdn.com/video/example.m3u8'))

    def test_douyin_waits_for_delayed_audio_after_video(self):
        videos = [{'url': 'https://cdn.example/media-video-avc1'}]

        self.assertFalse(_media_candidates_ready(True, videos, []))
        self.assertTrue(_media_candidates_ready(
            True, videos, [{'url': 'https://cdn.example/media-audio'}]
        ))
        self.assertTrue(_media_candidates_ready(False, videos, []))

    def test_douyin_audio_urls_are_recognized_across_cdn_variants(self):
        self.assertTrue(_is_audio_response(
            'https://v.douyinvod.com/media-audio/?codec_name=mp4a',
            'application/octet-stream',
        ))
        self.assertTrue(_is_audio_response(
            'https://v.douyinvod.com/play?mime_type=audio_mp4',
            'application/octet-stream',
        ))
        self.assertTrue(_is_audio_response(
            'https://v.douyinvod.com/opaque', 'audio/mp4'
        ))
        self.assertFalse(_is_audio_response(
            'https://v.douyinvod.com/media-video-avc1', 'video/mp4'
        ))

    def test_kuaishou_download_explains_the_manual_retry_step_without_yt_dlp_delay(self):
        progress = []
        with tempfile.TemporaryDirectory() as output_dir:
            with patch('lib.downloader.find_ffmpeg', return_value=None), patch(
                'lib.downloader._run_playwright_intercept',
                return_value={'success': False, 'error': 'verification required'},
            ) as intercept:
                result = downloader.download_video(
                    'https://v.m.chenzhongtech.com/fw/photo/3xgspcsnjj4dfv9?cc=share_wxms',
                    output_dir,
                    progress_callback=progress.append,
                )

        self.assertFalse(result['success'])
        intercept.assert_called_once()
        self.assertTrue(intercept.call_args.kwargs['allow_interactive_verification'])
        self.assertTrue(callable(intercept.call_args.kwargs['progress_callback']))
        self.assertIn('点击重试', progress[0]['stage'])
        self.assertIn('点击重试', progress[0]['message'])
        self.assertTrue(progress[0]['action_required'])

    def test_direct_browser_download_reports_real_byte_progress(self):
        class Response(io.BytesIO):
            headers = {'Content-Length': '12'}
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        progress = []
        with tempfile.TemporaryDirectory() as output_dir, patch(
            'lib.http_download.urllib.request.urlopen',
            return_value=Response(b'123456789012'),
        ):
            result = _download_file(
                'https://cdn.example/video.mp4', '测试视频', output_dir,
                progress_callback=progress.append,
            )

        self.assertTrue(result['success'])
        self.assertTrue(progress)
        self.assertEqual(progress[-1]['stage'], '正在下载视频')
        self.assertEqual(progress[-1]['progress'], 99)

    def test_separate_audio_is_merged_without_reencoding_video(self):
        with tempfile.TemporaryDirectory() as output_dir:
            video = f'{output_dir}/video.mp4'
            audio = f'{output_dir}/audio.m4a'
            with open(video, 'wb') as stream:
                stream.write(b'video')
            with open(audio, 'wb') as stream:
                stream.write(b'audio')

            def fake_run(command, **_kwargs):
                self.assertIn('-c:v', command)
                self.assertEqual(command[command.index('-c:v') + 1], 'copy')
                with open(f'{video}.merged.mp4', 'wb') as stream:
                    stream.write(b'merged')
                return type('Completed', (), {'returncode': 0})()

            with patch('lib.playwright_downloader.subprocess.run', side_effect=fake_run):
                self.assertTrue(_merge_audio(video, audio, 'ffmpeg'))

            with open(video, 'rb') as stream:
                self.assertEqual(stream.read(), b'merged')


if __name__ == '__main__':
    unittest.main()
