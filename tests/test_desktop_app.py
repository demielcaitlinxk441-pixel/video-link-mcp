import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton

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
        self.assertFalse(self.window.pause_button.isEnabled())
        self.assertTrue(self.window.queue_summary.isHidden())
        self.assertEqual(self.window.pause_button.minimumWidth(), 104)
        self.assertEqual(self.window.pause_button.maximumWidth(), 104)

    def test_download_queue_stays_directly_below_the_save_location(self):
        self.window.show()
        self.app.processEvents()

        self.assertGreater(self.window.queue_title.y(), self.window.destination_path.y())
        self.assertLess(self.window.queue_title.y() - self.window.destination_path.y(), 110)

    def test_first_screen_has_no_promotional_heading(self):
        self.assertIsNone(self.window.findChild(QLabel, 'brand'))
        self.assertIsNone(self.window.findChild(QLabel, 'eyebrow'))
        self.assertIsNone(self.window.findChild(QLabel, 'title'))

    def test_multiple_links_start_two_jobs_and_keep_the_rest_waiting(self):
        self.window.url.setPlainText('https://example.com/one\nhttps://example.com/two\nhttps://example.com/three')
        with patch('desktop_app.threading.Thread') as thread:
            self.window.start_download()

        self.assertEqual(len(self.window.jobs), 3)
        self.assertEqual(len(self.window.active_job_ids), 2)
        self.assertEqual(len(self.window.pending_job_ids), 1)
        self.assertEqual(thread.call_count, 2)
        self.assertIn('2 个下载中', self.window.queue_summary.text())
        self.assertIn('1 个等待', self.window.queue_summary.text())
        self.assertFalse(self.window.queue_summary.isHidden())

    def test_kuaishou_link_shows_notice_before_starting_the_download(self):
        self.window.url.setPlainText('https://www.kuaishou.com/f/share-token')
        with patch.object(self.window, '_show_kuaishou_notice', return_value=True) as notice, patch(
            'desktop_app.threading.Thread'
        ) as thread:
            self.window.start_download()

        notice.assert_called_once()
        self.assertEqual(len(self.window.jobs), 1)
        self.assertEqual(thread.call_count, 1)

    def test_cancelling_kuaishou_notice_keeps_the_link_and_does_not_start_a_job(self):
        link = 'https://www.kuaishou.com/f/share-token'
        self.window.url.setPlainText(link)
        with patch.object(self.window, '_show_kuaishou_notice', return_value=False), patch(
            'desktop_app.threading.Thread'
        ) as thread:
            self.window.start_download()

        self.assertEqual(self.window.url.toPlainText(), link)
        self.assertEqual(self.window.jobs, {})
        thread.assert_not_called()

    def test_pause_button_can_resume_a_waiting_queue_and_resets_when_empty(self):
        self.window.jobs['waiting-1'] = {
            'id': 'waiting-1', 'url': 'https://example.com/one', 'status': 'waiting'
        }
        self.window.pending_job_ids = ['waiting-1']
        self.window._render_jobs()
        self.assertTrue(self.window.pause_button.isEnabled())

        self.window.toggle_pause()
        self.assertTrue(self.window.paused)
        self.assertEqual(self.window.pause_button.text(), '继续队列')
        self.assertTrue(self.window.pause_button.isEnabled())

        with patch.object(self.window, '_start_pending_jobs') as start:
            self.window.toggle_pause()
        self.assertFalse(self.window.paused)
        self.assertFalse(self.window.hint.isVisible())
        start.assert_called_once()

        self.window.jobs.clear()
        self.window.pending_job_ids.clear()
        self.window.paused = True
        self.window._render_jobs()
        self.assertFalse(self.window.paused)
        self.assertFalse(self.window.pause_button.isEnabled())

    def test_share_text_extracts_only_unique_links(self):
        text = '复制此链接 https://example.com/one/，再看 https://example.com/two/ https://example.com/one/'
        self.assertEqual(
            self.window._extract_urls(text),
            ['https://example.com/one/', 'https://example.com/two/'],
        )

    def test_packaged_app_icon_exists(self):
        self.assertTrue((desktop_app.ROOT / 'assets' / 'video-download-round.ico').is_file())

    def test_finished_download_moves_the_item_from_queue_to_recent_downloads(self):
        job_id = 'download-1'
        self.window.jobs[job_id] = {
            'id': job_id, 'url': 'https://example.com/video', 'title': 'https://example.com/video',
            'status': 'active', 'stage': '正在下载', 'progress': 30, 'meta': '',
        }
        self.window.job_order.append(job_id)
        self.window.active_job_ids.add(job_id)
        self.window.task_card.show()
        with patch('desktop_app._save_history') as save, patch.object(self.window, '_load_history'):
            self.window._finished(job_id, {
                'success': True,
                'video_path': 'C:/downloads/video (兼容版).mp4',
                'size': 1024 * 1024,
                'metadata': {'title': '测试视频'},
                'compatibility': {'status': 'converted', 'source_removed': True},
            })

        self.assertNotIn(job_id, self.window.jobs)
        self.assertNotIn(job_id, self.window.job_order)
        self.assertTrue(self.window.task_card.isHidden())
        self.assertEqual(save.call_args.args[0]['title'], '测试视频')

    def test_download_row_keeps_only_title_and_progress_without_scrollbars(self):
        row = self.window._job_row({
            'id': 'download-1', 'url': 'https://example.com/video', 'title': '测试视频',
            'status': 'active', 'stage': '正在下载视频', 'progress': 40,
        })

        self.assertEqual(len(row.findChildren(QLabel, 'jobTitle')), 1)
        progress = row.findChildren(QProgressBar)[0]
        self.assertEqual(progress.value(), 40)
        self.assertTrue(progress.isTextVisible())
        self.assertEqual(progress.format(), '下载中 %p%')
        self.assertEqual(row.findChildren(QPushButton), [])
        self.assertEqual(
            self.window.task_scroll.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertEqual(
            self.window.task_scroll.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )

    def test_right_click_action_deletes_the_selected_record_and_video_file(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / '测试视频.mp4'
            video.write_bytes(b'video')
            record = {
                'id': 'download-1',
                'title': '测试视频',
                'video_path': str(video),
                'size': 1024,
            }
            with patch('desktop_app._history', return_value=[record]):
                self.window._load_history()
                self.window.history.setCurrentRow(0)
                with patch('desktop_app._remove_history_entry') as remove:
                    self.window.delete_history_with_file()

            self.assertFalse(video.exists())
        remove.assert_called_once_with('download-1')
        self.assertFalse(self.window.hint.isVisible())
        self.assertEqual(self.window.hint.text(), '')
        self.assertFalse(hasattr(self.window, 'delete_history_button'))



if __name__ == '__main__':
    unittest.main()
