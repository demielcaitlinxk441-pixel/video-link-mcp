import io
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from lib.http_download import DownloadCancelled, download_with_resume


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

    def test_cancel_keeps_partial_file_for_future_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'video.mp4'
            with self.assertRaises(DownloadCancelled):
                download_with_resume(
                    'https://cdn.example/video', str(target),
                    cancel_callback=lambda: True,
                )


if __name__ == '__main__':
    unittest.main()
