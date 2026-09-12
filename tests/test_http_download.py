import io
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from lib.http_download import DownloadCancelled, DownloadHTTPError, download_with_resume


class Response(io.BytesIO):
    def __init__(self, content: bytes, *, status: int = 200, headers: dict | None = None):
        super().__init__(content)
        self.status = status
        self.headers = headers or {'Content-Length': str(len(content))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class HttpDownloadTests(unittest.TestCase):
    def test_wrong_resume_offset_does_not_corrupt_saved_data(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'video.mp4'
            partial = Path(f'{target}.part'); partial.write_bytes(b'hello')
            with patch('lib.http_download.urllib.request.urlopen', return_value=Response(
                b'wrong', status=206, headers={'Content-Range': 'bytes 0-4/10'}
            )), self.assertRaises(OSError):
                download_with_resume('https://example.com/video', str(target), max_attempts=1)
            self.assertEqual(partial.read_bytes(), b'hello')
            self.assertFalse(target.exists())

    def test_empty_response_is_not_published_as_finished_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'video.mp4'
            with patch('lib.http_download.urllib.request.urlopen', return_value=Response(b'')), self.assertRaises(OSError):
                download_with_resume('https://example.com/video', str(target), max_attempts=1)
            self.assertFalse(target.exists())

    def test_network_failure_retries_and_finishes_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'video.mp4'
            with patch(
                'lib.http_download.urllib.request.urlopen',
                side_effect=[urllib.error.URLError('temporary'), Response(b'complete')],
            ) as open_url, patch('lib.http_download.time.sleep'):
                size = download_with_resume('https://cdn.example/video', str(target))

            self.assertEqual(size, 8)
            self.assertEqual(target.read_bytes(), b'complete')
            self.assertFalse(Path(f'{target}.part').exists())
            self.assertEqual(open_url.call_count, 2)

    def test_existing_partial_file_uses_range_resume(self):
        captured = []

        def open_url(request, timeout):
            captured.append((request.headers, timeout))
            return Response(
                b'world', status=206,
                headers={'Content-Length': '5', 'Content-Range': 'bytes 5-9/10'},
            )

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'video.mp4'
            Path(f'{target}.part').write_bytes(b'hello')
            with patch('lib.http_download.urllib.request.urlopen', side_effect=open_url):
                size = download_with_resume('https://cdn.example/video', str(target))

            self.assertEqual(size, 10)
            self.assertEqual(target.read_bytes(), b'helloworld')
            self.assertEqual(captured[0][0]['Range'], 'bytes=5-')
            self.assertEqual(captured[0][1], 30)

    def test_cancel_keeps_partial_file_for_future_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'video.mp4'
            with self.assertRaises(DownloadCancelled):
                download_with_resume(
                    'https://cdn.example/video', str(target),
                    cancel_callback=lambda: True,
                )

    def test_authorization_error_does_not_retry(self):
        error = urllib.error.HTTPError(
            'https://cdn.example/video', 403, 'Forbidden', {}, None
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            'lib.http_download.urllib.request.urlopen', side_effect=error
        ) as open_url:
            with self.assertRaises(DownloadHTTPError) as raised:
                download_with_resume('https://cdn.example/video', str(Path(directory) / 'video.mp4'))
        self.assertEqual(raised.exception.status, 403)
        self.assertEqual(open_url.call_count, 1)

    def test_rate_limit_waits_with_countdown_then_resumes(self):
        error = urllib.error.HTTPError(
            'https://cdn.example/video', 429, 'Too Many Requests', {}, None
        )
        events = []
        with tempfile.TemporaryDirectory() as directory, patch(
            'lib.http_download.urllib.request.urlopen',
            side_effect=[error, Response(b'complete')],
        ), patch('lib.http_download.time.sleep'):
            size = download_with_resume(
                'https://cdn.example/video', str(Path(directory) / 'video.mp4'),
                progress_callback=events.append,
            )
        self.assertEqual(size, 8)
        self.assertEqual([item['retry_in'] for item in events if 'retry_in' in item], [5, 4, 3, 2, 1])

    def test_service_error_retries_with_range_partial_preserved(self):
        error = urllib.error.HTTPError(
            'https://cdn.example/video', 503, 'Unavailable', {}, None
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'video.mp4'
            Path(f'{target}.part').write_bytes(b'hello')
            with patch(
                'lib.http_download.urllib.request.urlopen',
                side_effect=[error, Response(b'world', status=206, headers={
                    'Content-Length': '5', 'Content-Range': 'bytes 5-9/10'
                })],
            ), patch('lib.http_download.time.sleep'):
                size = download_with_resume('https://cdn.example/video', str(target))
            self.assertEqual(size, 10)
            self.assertEqual(target.read_bytes(), b'helloworld')


if __name__ == '__main__':
    unittest.main()
