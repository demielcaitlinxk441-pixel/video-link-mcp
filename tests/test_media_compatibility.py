from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from lib import downloader


H264_AAC_MP4 = {
    'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2'},
    'streams': [
        {'codec_type': 'video', 'codec_name': 'h264', 'pix_fmt': 'yuv420p'},
        {'codec_type': 'audio', 'codec_name': 'aac'},
    ],
}
AV1_MP4 = {
    'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2'},
    'streams': [
        {'codec_type': 'video', 'codec_name': 'av1', 'pix_fmt': 'yuv420p'},
        {'codec_type': 'audio', 'codec_name': 'aac'},
    ],
}
VIDEO_ONLY_MP4 = {
    'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2'},
    'streams': [
        {'codec_type': 'video', 'codec_name': 'h264', 'pix_fmt': 'yuv420p'},
    ],
}


class MediaCompatibilityTests(unittest.TestCase):
    def test_ffmpeg_helpers_request_a_hidden_windows_process(self):
        options = downloader._hidden_process_kwargs()
        if sys.platform != 'win32':
            self.assertEqual(options, {})
            return

        self.assertEqual(options.get('creationflags'), downloader.subprocess.CREATE_NO_WINDOW)
        self.assertEqual(options['startupinfo'].wShowWindow, downloader.subprocess.SW_HIDE)

    def test_h264_aac_yuv420p_mp4_is_high_compatibility(self):
        self.assertTrue(downloader._is_high_compatibility_mp4(H264_AAC_MP4))
        self.assertFalse(downloader._is_high_compatibility_mp4(AV1_MP4))
        self.assertFalse(downloader._is_high_compatibility_mp4(VIDEO_ONLY_MP4))

    def test_compatible_file_is_verified_without_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'video.mp4'
            source.write_bytes(b'video')
            result = {'success': True, 'video_path': str(source), 'size': 5}
            with patch('lib.downloader._find_ffprobe', return_value='ffprobe'), \
                 patch('lib.downloader._probe_media', return_value=H264_AAC_MP4), \
                 patch('lib.downloader._decode_check', return_value=True), \
                 patch('lib.downloader._transcode_to_compatible_mp4') as transcode:
                checked = downloader._ensure_compatible_video(
                    result, 'ffmpeg', lambda _: None
                )

        self.assertEqual(checked['compatibility']['status'], 'already_compatible')
        self.assertEqual(checked['video_path'], str(source))
        transcode.assert_not_called()

    def test_non_compatible_file_uses_only_a_verified_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'video.mp4'
            source.write_bytes(b'old')
            result = {'success': True, 'video_path': str(source), 'size': 3}

            def fake_transcode(_, target, __):
                Path(target).write_bytes(b'converted')
                return True

            with patch('lib.downloader._find_ffprobe', return_value='ffprobe'), \
                 patch('lib.downloader._probe_media', side_effect=[AV1_MP4, H264_AAC_MP4]), \
                 patch('lib.downloader._decode_check', return_value=True), \
                 patch('lib.downloader._transcode_to_compatible_mp4', side_effect=fake_transcode):
                checked = downloader._ensure_compatible_video(
                    result, 'ffmpeg', lambda _: None
                )

                self.assertEqual(checked['compatibility']['status'], 'converted')
                self.assertEqual(checked['source_video_path'], str(source))
                self.assertTrue(checked['compatibility']['source_removed'])
                self.assertFalse(source.exists())
                self.assertTrue(checked['video_path'].endswith(' (兼容版).mp4'))
                self.assertTrue(Path(checked['video_path']).is_file())

    def test_missing_ffmpeg_keeps_the_original_file_and_explains_why(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'video.mp4'
            source.write_bytes(b'old')
            result = {'success': True, 'video_path': str(source)}
            with patch('lib.downloader._find_ffprobe', return_value='ffprobe'), \
                 patch('lib.downloader._probe_media', return_value=AV1_MP4):
                checked = downloader._ensure_compatible_video(
                    result, None, lambda _: None
                )

        self.assertEqual(checked['compatibility']['status'], 'conversion_unavailable')
        self.assertEqual(checked['video_path'], str(source))

    def test_video_without_audio_is_reported_as_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'silent.mp4'
            source.write_bytes(b'video')
            result = {'success': True, 'video_path': str(source), 'size': 5}
            with patch('lib.downloader._find_ffprobe', return_value='ffprobe'), \
                 patch('lib.downloader._probe_media', return_value=VIDEO_ONLY_MP4):
                checked = downloader._ensure_compatible_video(
                    result, 'ffmpeg', lambda _: None
                )

        self.assertFalse(checked['success'])
        self.assertEqual(checked['compatibility']['status'], 'missing_audio')
        self.assertNotIn('Firefox', checked['error'])
        self.assertIn('Chrome/Edge', checked['error'])

    def test_decode_check_samples_the_start_and_end_of_long_videos(self):
        calls = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            return type('Completed', (), {'returncode': 0})()

        with patch('lib.downloader.subprocess.run', side_effect=fake_run):
            self.assertTrue(downloader._decode_check('video.mp4', 'ffmpeg', 120))

        self.assertEqual(len(calls), 2)
        self.assertIn('-t', calls[0])
        self.assertIn('-sseof', calls[1])

    def test_ffmpeg_location_is_cached(self):
        downloader.find_ffmpeg.cache_clear()
        try:
            with patch('lib.downloader.shutil.which', return_value='/usr/bin/ffmpeg') as which:
                self.assertEqual(downloader.find_ffmpeg(), '/usr/bin/ffmpeg')
                self.assertEqual(downloader.find_ffmpeg(), '/usr/bin/ffmpeg')
            which.assert_called_once_with('ffmpeg')
        finally:
            downloader.find_ffmpeg.cache_clear()

    def test_verified_conversion_keeps_both_files_when_source_deletion_is_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'video.mp4'
            source.write_bytes(b'old')
            result = {'success': True, 'video_path': str(source), 'size': 3}

            def fake_transcode(_, target, __):
                Path(target).write_bytes(b'converted')
                return True

            with patch('lib.downloader._find_ffprobe', return_value='ffprobe'), \
                 patch('lib.downloader._probe_media', side_effect=[AV1_MP4, H264_AAC_MP4]), \
                 patch('lib.downloader._decode_check', return_value=True), \
                 patch('lib.downloader._transcode_to_compatible_mp4', side_effect=fake_transcode), \
                 patch('lib.downloader.os.remove', side_effect=PermissionError):
                checked = downloader._ensure_compatible_video(
                    result, 'ffmpeg', lambda _: None
                )

            self.assertEqual(checked['compatibility']['status'], 'converted')
            self.assertFalse(checked['compatibility']['source_removed'])
            self.assertTrue(source.is_file())
            self.assertTrue(Path(checked['video_path']).is_file())


if __name__ == '__main__':
    unittest.main()
