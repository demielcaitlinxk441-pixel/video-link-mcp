from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SetupScriptContractTests(unittest.TestCase):
    def test_windows_setup_uses_default_pip_index_and_runs_checks(self):
        script = (ROOT / 'setup.bat').read_text(encoding='utf-8')
        self.assertNotIn('pypi.tuna.tsinghua.edu.cn', script)
        self.assertIn('diagnose.py', script)
        self.assertIn('test_server.py', script)

    def test_posix_setup_supports_optional_stt(self):
        script = (ROOT / 'setup.sh').read_text(encoding='utf-8')
        self.assertIn('--with-stt', script)
        self.assertIn('playwright install chromium', script)
        self.assertIn('-m venv', script)

    def test_dependency_files_are_pinned(self):
        core = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
        stt = (ROOT / 'requirements-stt.txt').read_text(encoding='utf-8')
        self.assertIn('mcp==1.28.1', core)
        self.assertIn('faster-whisper==1.2.1', stt)


if __name__ == '__main__':
    unittest.main()
