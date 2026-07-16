from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SetupScriptContractTests(unittest.TestCase):
    def test_windows_setup_uses_default_pip_index_and_runs_checks(self):
        script = (ROOT / 'setup.bat').read_text(encoding='utf-8')
        self.assertNotIn('pypi.tuna.tsinghua.edu.cn', script)
        self.assertIn('diagnose.py', script)
        self.assertIn('scripts\\verify.py', script)
        self.assertIn('create_desktop_shortcut.ps1', script)
        self.assertIn('start_desktop_app.bat', script)
        self.assertIn('VideoLinkAnalyzer\\runtime', script)
        self.assertIn('setlocal EnableDelayedExpansion', script)
        self.assertIn('if !PROJECT_PATH_LENGTH! GTR 80', script)

    def test_windows_launchers_fall_back_to_the_short_runtime_directory(self):
        for filename in ('start_desktop_app.bat', 'start_http_mcp.bat', 'download_with_cookies.bat'):
            script = (ROOT / 'scripts' / filename).read_text(encoding='utf-8')
            self.assertIn('VideoLinkAnalyzer\\runtime', script)

    def test_windows_setup_prints_http_mcp_start_command(self):
        script = (ROOT / 'setup.bat').read_text(encoding='utf-8')
        self.assertIn('scripts\\start_http_mcp.bat', script)
        self.assertIn('http://127.0.0.1:8000/mcp', script)

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
