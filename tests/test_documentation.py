from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_installation_guide_replaces_private_setup_document(self):
        guide = ROOT / 'docs' / 'installation-and-troubleshooting.md'

        self.assertTrue(guide.is_file())
        self.assertFalse((ROOT / 'docs' / 'private-github-setup.md').exists())
        self.assertIn('安装与排错指南', guide.read_text(encoding='utf-8'))

    def test_readme_links_to_installation_guide(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')

        self.assertIn('docs/installation-and-troubleshooting.md', readme)


if __name__ == '__main__':
    unittest.main()
