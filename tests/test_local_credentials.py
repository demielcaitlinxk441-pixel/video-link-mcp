import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lib import local_credentials


class LocalCredentialTests(unittest.TestCase):
    def test_platform_credentials_are_stored_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            credential_file = Path(directory) / 'credentials.json'
            with patch.object(local_credentials, 'APP_DIR', Path(directory)), \
                 patch.object(local_credentials, 'CREDENTIALS_FILE', credential_file), \
                 patch.object(local_credentials, '_protect', side_effect=lambda value: f'enc:{value[::-1]}'), \
                 patch.object(local_credentials, '_unprotect', side_effect=lambda value: value.removeprefix('enc:')[::-1]):
                local_credentials.save_yuanbao_cookie('yuanbao-secret')
                local_credentials.save_bilibili_cookie('bilibili-secret')
                local_credentials.save_douyin_cookie('douyin-secret')

                stored = json.loads(credential_file.read_text(encoding='utf-8'))
                self.assertNotIn('yuanbao-secret', credential_file.read_text(encoding='utf-8'))
                self.assertEqual(set(stored), {'yuanbao_cookie', 'bilibili_cookie', 'douyin_cookie'})
                self.assertEqual(local_credentials.get_yuanbao_cookie(), 'yuanbao-secret')
                self.assertEqual(local_credentials.get_bilibili_cookie(), 'bilibili-secret')
                self.assertEqual(local_credentials.get_douyin_cookie(), 'douyin-secret')

                local_credentials.clear_bilibili_cookie()
                self.assertEqual(local_credentials.get_yuanbao_cookie(), 'yuanbao-secret')
                self.assertEqual(local_credentials.get_bilibili_cookie(), '')
                self.assertEqual(local_credentials.get_douyin_cookie(), 'douyin-secret')


if __name__ == '__main__':
    unittest.main()
