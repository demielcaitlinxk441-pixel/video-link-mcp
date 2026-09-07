import unittest

from lib.detector import detect_link_type
from lib.download_diagnostics import normalize_result


class PlatformAcceptanceMatrixTests(unittest.TestCase):
    def test_required_platforms_are_identified_before_download(self):
        cases = {
            'https://v.douyin.com/example/': 'Douyin',
            'https://b23.tv/example': 'Bilibili',
            'https://youtu.be/example': 'YouTube',
            'https://v.m.chenzhongtech.com/fw/photo/example': 'Kuaishou',
            'https://weixin.qq.com/sph/example': 'WeChat Channels',
        }
        for url, platform in cases.items():
            with self.subTest(platform=platform):
                result = detect_link_type(url)
                self.assertEqual(result['type'], 'video')
                self.assertEqual(result['platform'], platform)

    def test_plain_direct_mp4_is_identified(self):
        result = detect_link_type('https://cdn.example.com/media/video.mp4')
        self.assertEqual(result['type'], 'video')

    def test_platform_refusal_keeps_actionable_failure_contract(self):
        for status, code in ((429, 'RATE_LIMITED'), (403, 'AUTH_REQUIRED'), (503, 'SERVICE_UNAVAILABLE')):
            with self.subTest(status=status):
                result = normalize_result({
                    'success': False, 'error': f'HTTP Error {status}',
                    'download_method': 'yt-dlp', 'attempts': 3,
                }, url='https://example.com/video?token=secret')
                self.assertEqual(result['error_code'], code)
                self.assertTrue(result['suggested_action'])
                self.assertNotIn('secret', str(result['diagnostics']))


if __name__ == '__main__':
    unittest.main()
