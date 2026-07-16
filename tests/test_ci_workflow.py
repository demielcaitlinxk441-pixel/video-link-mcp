from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CiWorkflowTests(unittest.TestCase):
    def test_workflow_runs_offline_unittest_suite(self):
        workflow = (ROOT / '.github/workflows/test.yml').read_text(encoding='utf-8')
        self.assertIn('python -m unittest discover -s tests -v', workflow)
        self.assertIn('actions/setup-python', workflow)
        self.assertIn('ubuntu-latest', workflow)
        self.assertIn('windows-latest', workflow)
        self.assertNotIn('WECHAT_CHANNELS_YUANBAO_COOKIE', workflow)


if __name__ == '__main__':
    unittest.main()
