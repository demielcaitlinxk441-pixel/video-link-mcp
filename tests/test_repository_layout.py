from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryLayoutTests(unittest.TestCase):
    def test_auxiliary_scripts_are_grouped_under_scripts_directory(self):
        scripts = ROOT / 'scripts'
        for filename in (
            'download_direct.py',
            'intercept_download.py',
            'download_with_cookies.bat',
            'verify.py',
        ):
            self.assertTrue((scripts / filename).is_file())
            self.assertFalse((ROOT / filename).exists())

    def test_internal_agent_documents_are_not_published(self):
        self.assertFalse((ROOT / 'docs' / 'superpowers').exists())

    def test_python_scripts_import_from_the_project_root(self):
        for filename in ('download_direct.py', 'intercept_download.py', 'verify.py'):
            source = (ROOT / 'scripts' / filename).read_text(encoding='utf-8')
            self.assertIn('PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))', source)
            self.assertIn('sys.path.insert(0, PROJECT_ROOT)', source)

    def test_cookie_download_script_points_to_parent_virtual_environment(self):
        source = (ROOT / 'scripts' / 'download_with_cookies.bat').read_text(encoding='utf-8')
        self.assertIn('set "PYTHON=%~dp0..\\venv\\Scripts\\python.exe"', source)

    def test_http_start_script_uses_project_virtual_environment(self):
        source = (ROOT / 'scripts' / 'start_http_mcp.bat').read_text(encoding='utf-8')
        self.assertIn('venv\\Scripts\\python.exe', source)
        self.assertIn('server.py" --transport http', source)

    def test_windows_desktop_launcher_uses_the_project_virtual_environment(self):
        source = (ROOT / 'scripts' / 'start_desktop_app.bat').read_text(encoding='utf-8')
        self.assertIn('venv\\Scripts\\pythonw.exe', source)
        self.assertIn('desktop_app.py', source)

    def test_desktop_shortcut_uses_the_desktop_launcher_and_app_icon(self):
        source = (ROOT / 'scripts' / 'create_desktop_shortcut.ps1').read_text(encoding='utf-8')
        self.assertIn('assets\\app-icon.ico', source)
        self.assertIn('start_desktop_app.bat', source)

    def test_http_example_uses_loopback_url(self):
        source = (ROOT / 'mcp_http_config_example.json').read_text(encoding='utf-8')
        self.assertIn('http://127.0.0.1:8000/mcp', source)
        self.assertNotIn('0.0.0.0', source)


if __name__ == '__main__':
    unittest.main()
