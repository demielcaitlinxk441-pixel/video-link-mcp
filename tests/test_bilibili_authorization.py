import unittest

from lib.bilibili_authorization import has_bilibili_login_cookie


class BilibiliAuthorizationTests(unittest.TestCase):
    def test_requires_bilibili_session_cookie(self):
        self.assertTrue(has_bilibili_login_cookie('buvid3=x; SESSDATA=secret; bili_jct=y'))
        self.assertFalse(has_bilibili_login_cookie('buvid3=x; bili_jct=y'))


if __name__ == '__main__':
    unittest.main()
