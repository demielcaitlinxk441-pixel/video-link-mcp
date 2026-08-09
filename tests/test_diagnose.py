import unittest
from unittest.mock import patch

import diagnose


class DiagnoseTests(unittest.TestCase):
    def test_collect_diagnostics_reports_all_capabilities(self):
        result = diagnose.collect_diagnostics()
        for name in (
            'python', 'supported_python', 'core_dependencies', 'ffmpeg',
            'ffmpeg_path', 'playwright_browser', 'speech_to_text', 'core_ready',
        ):
            self.assertIn(name, result)

    @patch('diagnose.find_ffmpeg', return_value=r'C:\\ffmpeg\\bin\\ffmpeg.exe')
    def test_ffmpeg_uses_the_downloader_locator(self, _):
        result = diagnose.collect_diagnostics()

        self.assertTrue(result['ffmpeg'])
        self.assertEqual(result['ffmpeg_path'], r'C:\\ffmpeg\\bin\\ffmpeg.exe')

    @patch('diagnose.importlib.util.find_spec', return_value=None)
    def test_core_ready_is_false_when_a_required_package_is_missing(self, _):
        self.assertFalse(diagnose.collect_diagnostics()['core_ready'])

    @patch('diagnose._chromium_is_installed', return_value=False)
    def test_core_ready_is_false_when_playwright_browser_is_missing(self, _):
        self.assertFalse(diagnose.collect_diagnostics()['core_ready'])


if __name__ == '__main__':
    unittest.main()
