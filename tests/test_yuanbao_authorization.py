import unittest

from lib.yuanbao_authorization import build_cookie_header


class YuanbaoAuthorizationTests(unittest.TestCase):
    def test_build_cookie_header_keeps_only_named_cookie_values(self):
        self.assertEqual(
            build_cookie_header([
                {'name': 'session', 'value': 'abc'},
                {'name': '', 'value': 'skip'},
                {'name': 'empty', 'value': ''},
                {'name': 'user', 'value': 42},
            ]),
            'session=abc; user=42',
        )


if __name__ == '__main__':
    unittest.main()