import unittest
from unittest.mock import patch

import diagnose


class DiagnoseTests(unittest.TestCase):
    def test_collect_diagnostics_reports_all_capabilities(self):
        result = diagnose.collect_diagnostics()
        for name in (
            'python', 'supported_python', 'core_dependencies', 'ffmpeg',
            'playwright_browser', 'speech_to_text', 'core_ready',
        ):
            self.assertIn(name, result)

    @patch('diagnose.importlib.util.find_spec', return_value=None)
    def test_core_ready_is_false_when_a_required_package_is_missing(self, _):
        self.assertFalse(diagnose.collect_diagnostics()['core_ready'])

    @patch('diagnose._chromium_is_installed', return_value=False)
    def test_core_ready_is_false_when_playwright_browser_is_missing(self, _):
        self.assertFalse(diagnose.collect_diagnostics()['core_ready'])


if __name__ == '__main__':
    unittest.main()
