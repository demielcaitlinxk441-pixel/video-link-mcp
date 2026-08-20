import unittest

from lib.detector import detect_video_platform


class DetectorTests(unittest.TestCase):
    def test_current_and_legacy_kuaishou_links_are_detected(self):
        for url in (
            'https://www.kuaishou.com/short-video/3xgspcsnjj4dfv9',
            'https://m.gifshow.com/fw/photo/3xgspcsnjj4dfv9',
            'https://v.m.chenzhongtech.com/fw/photo/3xgspcsnjj4dfv9?cc=share_wxms',
        ):
            with self.subTest(url=url):
                result = detect_video_platform(url)
                self.assertIsNotNone(result)
                self.assertEqual(result['platform_key'], 'kuaishou')


if __name__ == '__main__':
    unittest.main()
