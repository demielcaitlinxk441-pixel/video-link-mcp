import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

if sys.platform != 'win32':
    raise unittest.SkipTest('Windows desktop UI tests run on Windows CI only.')

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton

import desktop_app


class DesktopAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.queue_load = patch('desktop_app._load_queue', return_value=[])
        self.queue_save = patch('desktop_app._save_queue')
        self.queue_load.start(); self.queue_save.start()
        self.addCleanup(self.queue_load.stop); self.addCleanup(self.queue_save.stop)
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

        # These widgets live in different layouts, so their local y values
        # are not comparable. Compare their positions in the main window
        # coordinate system instead.
        destination_y = self.window.destination_path.mapTo(self.window, QPoint(0, 0)).y()
        queue_y = self.window.queue_title.mapTo(self.window, QPoint(0, 0)).y()
        self.assertGreater(queue_y, destination_y)
        self.assertLess(queue_y - destination_y, 160)

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
        self.window.url.setPlainText(
            'https://v.m.chenzhongtech.com/fw/photo/3xgspcsnjj4dfv9?cc=share_wxms'
        )
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

    def test_finished_silent_video_is_saved_with_an_audio_warning(self):
        job_id = 'download-silent'
        self.window.jobs[job_id] = {
            'id': job_id, 'url': 'https://example.com/video', 'title': 'https://example.com/video',
            'status': 'active', 'stage': '正在下载', 'progress': 30, 'meta': '',
        }
        self.window.job_order.append(job_id)
        self.window.active_job_ids.add(job_id)
        with patch('desktop_app._save_history') as save, patch.object(self.window, '_load_history'), patch.object(self.window, '_show_hint') as hint:
            self.window._finished(job_id, {
                'success': True,
                'video_path': 'C:/downloads/silent.mp4',
                'size': 1024,
                'metadata': {'title': '无声视频'},
                'compatibility': {'status': 'missing_audio', 'audio_missing': True},
            })

        self.assertEqual(save.call_args.args[0]['metadata']['audio_status'], 'missing')
        hint.assert_called_once_with('视频已保存，但未检测到音轨。')

    def test_download_row_keeps_compact_progress_and_cancel_action(self):
        row = self.window._job_row({
            'id': 'download-1', 'url': 'https://example.com/video', 'title': '测试视频',
            'status': 'active', 'stage': '正在下载视频', 'progress': 40,
        })

        self.assertEqual(len(row.findChildren(QLabel, 'jobTitle')), 1)
        progress = row.findChildren(QProgressBar)[0]
        self.assertEqual(progress.value(), 40)
        self.assertTrue(progress.isTextVisible())
        self.assertEqual(progress.format(), '下载中 %p%')
        buttons = row.findChildren(QPushButton)
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].text(), '取消')
        self.assertEqual(
            self.window.task_scroll.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertEqual(
            self.window.task_scroll.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )

    def test_plaintext_ai_key_is_migrated_out_of_settings(self):
        settings = {'ai': {'provider': 'OpenAI', 'api_key': 'secret-key'}}
        with patch('desktop_app.save_ai_api_key') as save_key, \
             patch('desktop_app._save_settings') as save_settings:
            desktop_app._migrate_plaintext_ai_key(settings)

        save_key.assert_called_once_with('secret-key')
        self.assertNotIn('api_key', settings['ai'])
        save_settings.assert_called_once_with(settings)

    def test_cancel_active_job_signals_worker(self):
        import threading

        self.window.jobs['active-1'] = {
            'id': 'active-1', 'url': 'https://example.com/video',
            'title': '测试视频', 'status': 'active', 'stage': '正在下载',
        }
        self.window.job_order = ['active-1']
        self.window.cancel_events['active-1'] = threading.Event()

        self.window.cancel_job('active-1')

        self.assertTrue(self.window.cancel_events['active-1'].is_set())
        self.assertEqual(self.window.jobs['active-1']['stage'], '正在取消')

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

    def test_audio_retry_reuses_saved_video_and_does_not_queue_full_download(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / 'silent.mp4'
            video.write_bytes(b'video')
            record = {
                'id': 'silent-1', 'title': '无声视频', 'video_path': str(video),
                'metadata': {'audio_status': 'missing', 'source_url': 'https://example.com/video'},
            }
            with patch('desktop_app._history', return_value=[record]):
                self.window._load_history()
                self.window.history.setCurrentRow(0)
                with patch('desktop_app.threading.Thread') as thread:
                    self.window.retry_history_audio()

            job = next(iter(self.window.jobs.values()))
            self.assertEqual(job['mode'], 'retry_audio')
            self.assertEqual(job['video_path'], str(video))
            self.assertEqual(job['url'], 'https://example.com/video')
            self.assertEqual(thread.call_count, 1)

    def test_subtitle_retry_does_not_queue_media_download(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / 'video.mp4'
            video.write_bytes(b'video')
            record = {
                'id': 'subtitle-1', 'title': '字幕失败视频', 'video_path': str(video),
                'metadata': {'subtitle_status': 'failed', 'source_url': 'https://example.com/video'},
            }
            with patch('desktop_app._history', return_value=[record]):
                self.window._load_history()
                self.window.history.setCurrentRow(0)
                with patch('desktop_app.threading.Thread') as thread:
                    self.window.retry_history_subtitle()

            job = next(iter(self.window.jobs.values()))
            self.assertEqual(job['mode'], 'retry_subtitle')
            self.assertEqual(job['output_dir'], directory)
            self.assertEqual(thread.call_count, 1)

    def test_completed_source_url_is_not_downloaded_again(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / 'done.mp4'
            video.write_bytes(b'video')
            record = {
                'id': 'done-1', 'title': '完成视频', 'video_path': str(video),
                'metadata': {'source_url': 'https://example.com/done'},
            }
            self.window.url.setPlainText('https://example.com/done')
            with patch('desktop_app._history', return_value=[record]), \
                 patch('desktop_app.threading.Thread') as thread:
                self.window.start_download()

            self.assertEqual(self.window.jobs, {})
            thread.assert_not_called()
            self.assertIn('已经下载完成', self.window.hint.text())

    def test_interrupted_and_failed_jobs_restore_without_completed_jobs(self):
        saved = [
            {
                'id': 'active-1', 'url': 'https://example.com/a', 'status': 'active',
                'stage': '正在下载', 'output_dir': 'C:/downloads',
                'temporary_file': 'C:/downloads/a.mp4.part', 'attempts': 2,
            },
            {
                'id': 'failed-1', 'url': 'https://example.com/b', 'status': 'failed',
                'stage': '视频下载失败', 'output_dir': 'C:/downloads', 'attempts': 3,
            },
            {'id': 'done-1', 'url': 'https://example.com/c', 'status': 'completed'},
        ]
        self.window.jobs.clear(); self.window.job_order.clear()
        self.window.pending_job_ids.clear(); self.window.cancel_events.clear()
        with patch('desktop_app._load_queue', return_value=saved):
            self.window._restore_jobs()

        self.assertEqual(set(self.window.jobs), {'active-1', 'failed-1'})
        self.assertEqual(self.window.jobs['active-1']['status'], 'waiting')
        self.assertEqual(self.window.jobs['active-1']['temporary_file'], 'C:/downloads/a.mp4.part')
        self.assertEqual(self.window.pending_job_ids, ['active-1'])
        self.assertEqual(self.window.jobs['failed-1']['status'], 'failed')

    def test_queue_persistence_keeps_resume_metadata(self):
        self.window.jobs = {
            'job-1': {
                'id': 'job-1', 'url': 'https://example.com/video', 'status': 'active',
                'stage': '视频下载', 'output_dir': 'C:/downloads', 'attempts': 2,
                'video_id': 'abc', 'temporary_file': 'C:/downloads/a.part',
            }
        }
        self.window.job_order = ['job-1']
        with patch('desktop_app._save_queue') as save:
            self.window._persist_jobs()
        persisted = save.call_args.args[0][0]
        self.assertEqual(persisted['video_id'], 'abc')
        self.assertEqual(persisted['attempts'], 2)
        self.assertEqual(persisted['temporary_file'], 'C:/downloads/a.part')

    def test_failure_message_shows_reason_completed_content_and_action(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / 'silent.mp4'
            video.write_bytes(b'video')
            message = desktop_app._failure_display({
                'video_path': str(video),
                'failure': {'reason': '音频获取失败。', 'suggested_action': '重试音频。'},
            })
        self.assertIn('问题原因：音频获取失败', message)
        self.assertIn('已完成内容：画面已保存', message)
        self.assertIn('处理办法：重试音频', message)



if __name__ == '__main__':
    unittest.main()
