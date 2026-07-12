from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SmokeTestContractTests(unittest.TestCase):
    def test_smoke_test_exits_nonzero_when_a_check_fails(self):
        source = (ROOT / 'test_server.py').read_text(encoding='utf-8')
        self.assertIn('sys.exit(1 if failed else 0)', source)


if __name__ == '__main__':
    unittest.main()
