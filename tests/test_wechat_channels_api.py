import os
import unittest
from unittest.mock import patch

from lib import wechat_channels_api as api


class WorkerPrivacyTests(unittest.TestCase):
    def test_public_worker_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(api, '_parse_share_url_worker') as worker:
                self.assertIsNone(api.parse_share_link('https://weixin.qq.com/sph/example'))
        worker.assert_not_called()

    def test_public_worker_requires_true_flag(self):
        environment = {'WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER': 'true'}
        with patch.dict(os.environ, environment, clear=True):
            with patch.object(api, '_parse_share_url_worker', return_value={'feedInfo': {}}) as worker:
                result = api.parse_share_link('https://weixin.qq.com/sph/example')
        self.assertEqual(result, {'feedInfo': {}})
        worker.assert_called_once()

    def test_custom_worker_is_explicit_opt_in(self):
        environment = {'WECHAT_CHANNELS_WORKER_URL': 'https://worker.example/api'}
        with patch.dict(os.environ, environment, clear=True):
            with patch.object(api, '_parse_share_url_worker', return_value={'feedInfo': {}}) as worker:
                result = api.parse_share_link('https://weixin.qq.com/sph/example')
        self.assertEqual(result, {'feedInfo': {}})
        worker.assert_called_once()


if __name__ == '__main__':
    unittest.main()
