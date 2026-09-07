import unittest

from lib import downloader


class DownloadEfficiencyTests(unittest.TestCase):
    def test_default_format_prefers_h264_aac_mp4_and_limits_1080p(self):
        selector = downloader.DEFAULT_FORMAT_SELECTOR
        preferred = selector.split('/')[0]
        self.assertIn('vcodec^=avc1', preferred)
        self.assertIn('acodec^=mp4a', preferred)
        self.assertIn('height<=1080', preferred)
        self.assertIn('ext=mp4', preferred)

    def test_format_has_safe_fallbacks_after_compatible_choice(self):
        choices = downloader.DEFAULT_FORMAT_SELECTOR.split('/')
        self.assertGreaterEqual(len(choices), 4)
        self.assertIn('bestvideo+bestaudio', choices)
        self.assertEqual(choices[-1], 'best')


if __name__ == '__main__':
    unittest.main()
