from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OpenSourceMetadataTests(unittest.TestCase):
    def test_license_is_mit(self):
        license_text = (ROOT / 'LICENSE').read_text(encoding='utf-8')
        self.assertIn('MIT License', license_text)
        self.assertIn('Permission is hereby granted, free of charge', license_text)

    def test_readme_declares_mit_license(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('## 许可证', readme)
        self.assertIn('MIT License', readme)

    def test_public_repository_metadata_is_not_described_as_private(self):
        for filename in ('SECURITY.md', 'CHANGELOG.md'):
            content = (ROOT / filename).read_text(encoding='utf-8').lower()
            self.assertNotIn('private repository', content)


if __name__ == '__main__':
    unittest.main()
