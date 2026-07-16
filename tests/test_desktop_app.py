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

    def test_finished_download_explains_when_a_compatible_copy_was_created(self):
        self.window._finished({
            'success': True,
            'video_path': 'C:/downloads/video (兼容版).mp4',
            'size': 1024 * 1024,
            'metadata': {'title': '测试视频'},
            'compatibility': {'status': 'converted', 'source_removed': True},
        })

        self.assertEqual(self.window.task_stage.text(), '兼容 MP4 已验证')
        self.assertIn('原始文件已删除', self.window.task_meta.text())

    def test_delete_button_removes_only_the_selected_history_record(self):
        record = {
            'id': 'download-1',
            'title': '测试视频',
            'video_path': 'C:/downloads/video.mp4',
            'size': 1024,
        }
        with patch('desktop_app._history', return_value=[record]):
            self.window._load_history()
            self.assertFalse(self.window.delete_history_button.isEnabled())
            self.window.history.setCurrentRow(0)
            self.assertTrue(self.window.delete_history_button.isEnabled())
            with patch('desktop_app._remove_history_entry') as remove:
                self.window.delete_selected_history()

        remove.assert_called_once_with('download-1')
        self.assertIn('视频文件没有删除', self.window.hint.text())



if __name__ == '__main__':
    unittest.main()
