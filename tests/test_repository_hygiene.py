from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(unittest.TestCase):
    def test_gitignore_excludes_local_secrets_and_outputs(self):
        ignored = (ROOT / '.gitignore').read_text(encoding='utf-8')
        for rule in ('.env', 'venv/', 'outputs/', 'cookies.txt', '*.mp4', '*.key'):
            self.assertIn(rule, ignored)

    def test_env_example_contains_names_but_no_secret_values(self):
        lines = (ROOT / '.env.example').read_text(encoding='utf-8').splitlines()
        self.assertIn('WECHAT_CHANNELS_YUANBAO_COOKIE=', lines)
        self.assertIn('WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER=false', lines)

    def test_readme_documents_private_installation_and_worker_opt_in(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        for text in ('git clone', 'setup.bat', 'setup.sh', 'diagnose.py', 'WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER'):
            self.assertIn(text, readme)


if __name__ == '__main__':
    unittest.main()
