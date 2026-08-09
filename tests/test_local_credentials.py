import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lib import local_credentials


class LocalCredentialTests(unittest.TestCase):
    def test_credentials_are_stored_separately_and_clear_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            credential_file = Path(directory) / 'credentials.json'
            with patch.object(local_credentials, 'APP_DIR', Path(directory)), \
                 patch.object(local_credentials, 'CREDENTIALS_FILE', credential_file), \
                 patch.object(local_credentials, '_protect', side_effect=lambda value: f'enc:{value[::-1]}'), \
                 patch.object(local_credentials, '_unprotect', side_effect=lambda value: value.removeprefix('enc:')[::-1]):
                local_credentials.save_yuanbao_cookie('yuanbao-secret')
                local_credentials.save_ai_api_key('ai-secret')

                stored = json.loads(credential_file.read_text(encoding='utf-8'))
                self.assertNotIn('yuanbao-secret', credential_file.read_text(encoding='utf-8'))
                self.assertEqual(set(stored), {'yuanbao_cookie', 'ai_api_key'})
                self.assertEqual(local_credentials.get_yuanbao_cookie(), 'yuanbao-secret')
                self.assertEqual(local_credentials.get_ai_api_key(), 'ai-secret')

                local_credentials.clear_ai_api_key()
                self.assertEqual(local_credentials.get_ai_api_key(), '')
                self.assertEqual(local_credentials.get_yuanbao_cookie(), 'yuanbao-secret')


if __name__ == '__main__':
    unittest.main()
