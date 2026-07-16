import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

import desktop_app


class DesktopAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = desktop_app.MainWindow()
        self.addCleanup(self.window.close)

    def test_first_screen_hides_task_card_until_a_link_is_submitted(self):
        self.assertTrue(self.window.task_card.isHidden())
        self.assertTrue(self.window.hint.isHidden())

    def test_download_worker_reports_folder_or_downloader_failures(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            self.window.active_job = {'url': 'https://example.com/video'}
            self.window.output_dir = Path(temporary_directory) / 'downloads'
            with patch('desktop_app.download_video', side_effect=PermissionError('access denied')):
                self.window._download_worker()

        self.assertEqual(self.window.task_stage.text(), '下载失败')
        self.assertIn('access denied', self.window.task_meta.text())

    def test_packaged_app_icon_exists(self):
        self.assertTrue((desktop_app.ROOT / 'assets' / 'app-icon.ico').is_file())


if __name__ == '__main__':
    unittest.main()
