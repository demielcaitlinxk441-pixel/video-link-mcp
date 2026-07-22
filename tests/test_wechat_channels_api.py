import os
import unittest
from unittest.mock import patch

from lib import wechat_channels_api as api


class WorkerPrivacyTests(unittest.TestCase):
    def test_public_worker_is_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(api, '_resolve_yuanbao_cookie', return_value=''):
                with patch.object(api, '_parse_share_url_worker', return_value={'feedInfo': {}}) as worker:
                    result = api.parse_share_link('https://weixin.qq.com/sph/example')
        self.assertEqual(result, {'feedInfo': {}})
        worker.assert_called_once()

    def test_public_worker_requires_true_flag(self):
        environment = {'WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER': 'true'}
        with patch.dict(os.environ, environment, clear=True):
            with patch.object(api, '_resolve_yuanbao_cookie', return_value=''):
                with patch.object(api, '_parse_share_url_worker', return_value={'feedInfo': {}}) as worker:
                    result = api.parse_share_link('https://weixin.qq.com/sph/example')
        self.assertEqual(result, {'feedInfo': {}})
        worker.assert_called_once()

    def test_custom_worker_is_explicit_opt_in(self):
        environment = {'WECHAT_CHANNELS_WORKER_URL': 'https://worker.example/api'}
        with patch.dict(os.environ, environment, clear=True):
            with patch.object(api, '_resolve_yuanbao_cookie', return_value=''):
                with patch.object(api, '_parse_share_url_worker', return_value={'feedInfo': {}}) as worker:
                    result = api.parse_share_link('https://weixin.qq.com/sph/example')
        self.assertEqual(result, {'feedInfo': {}})
        worker.assert_called_once()

    def test_local_authorization_does_not_send_link_to_public_worker(self):
        with patch.object(api, '_fetch_video_profile_direct', return_value=None) as direct:
            with patch.object(api, '_parse_share_url_worker') as worker:
                result = api.parse_share_link(
                    'https://weixin.qq.com/sph/example', yuanbao_cookie='owner-cookie'
                )
        self.assertIsNone(result)
        direct.assert_called_once_with('https://weixin.qq.com/sph/example', 'owner-cookie')
        worker.assert_not_called()


if __name__ == '__main__':
    unittest.main()