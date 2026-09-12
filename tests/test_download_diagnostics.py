import unittest
from unittest.mock import patch

from lib.download_diagnostics import classify_failure, diagnostic_report, normalize_result
from lib import downloader


class DownloadDiagnosticsTests(unittest.TestCase):
    def test_status_codes_have_distinct_recovery_guidance(self):
        self.assertEqual(classify_failure('HTTP Error 503')['error_code'], 'SERVICE_UNAVAILABLE')
        self.assertEqual(classify_failure('HTTP Error 429')['error_code'], 'RATE_LIMITED')
        self.assertEqual(classify_failure('HTTP Error 412')['failed_stage'], '授权')

    def test_wechat_authorization_parse_failure_has_a_specific_recovery_action(self):
        failure = classify_failure('[WECHAT_CHANNELS_AUTH_PARSE_FAILED] 本机视频号授权无法解析此链接。')
        self.assertEqual(failure['error_code'], 'WECHAT_CHANNELS_AUTH_PARSE_FAILED')
        self.assertEqual(failure['failed_stage'], '授权')
        self.assertIn('视频号授权', failure['suggested_action'])

    def test_local_secrets_and_signed_parameters_are_redacted(self):
        report = diagnostic_report({
            'success': False,
            'error': 'Cookie=session-secret https://cdn.test/v.mp4?token=secret&sig=signature&quality=1',
            'video_path': f'{__import__("os").path.expanduser("~")}/Downloads/video.mp4',
        })
        self.assertNotIn('session-secret', report)
        self.assertNotIn('token=secret', report)
        self.assertNotIn('signature', report)
        self.assertNotIn(__import__('os').path.expanduser('~'), report)
        self.assertIn('已完成内容：video_path', report)

    def test_legacy_fields_remain_and_structured_fields_are_added(self):
        result = normalize_result({'success': False, 'error': 'HTTP Error 503'})
        self.assertIn('error', result)
        self.assertEqual(result['http_status'], 503)
        self.assertIn('failure', result)
        self.assertIn('artifacts', result)
        self.assertIn('diagnostics', result)

    def test_public_wrapper_normalizes_unhandled_file_errors(self):
        with patch('lib.downloader._download_video_impl', side_effect=PermissionError('Access is denied')):
            result = downloader.download_video('https://example.com/video')
        self.assertFalse(result['success'])
        self.assertEqual(result['failed_stage'], '文件保存')


if __name__ == '__main__':
    unittest.main()
