Exit code: 0
Wall time: 0.6 seconds
Output:
import threading
import unittest
from unittest.mock import patch

from lib import downloader


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


if __name__ == '__main__':
    unittest.main()

