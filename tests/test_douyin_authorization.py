import unittest

from lib.douyin_authorization import has_douyin_session_cookie


class DouyinAuthorizationTests(unittest.TestCase):
    def test_requires_a_session_marker(self):
        self.assertTrue(has_douyin_session_cookie('ttwid=x; sessionid=secret; odin_tt=y'))
        self.assertFalse(has_douyin_session_cookie('ttwid=x; odin_tt=y'))


if __name__ == '__main__':
    unittest.main()
