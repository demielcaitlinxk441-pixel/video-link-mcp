# Private GitHub Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the MCP server safe to distribute through a private GitHub repository and repeatably install on a fresh computer.

**Architecture:** Keep the stdio MCP server. Add a diagnostic command, platform setup scripts, repository metadata, and an explicit privacy gate around the default public WeChat Worker. No hosted service, Docker image, or binary release is added.

**Tech Stack:** Python 3.10–3.13, FastMCP, yt-dlp, Playwright, faster-whisper (optional), Bash, Windows batch, GitHub Actions.

## Global Constraints

- Repository root is `video-link-mcp/`; never initialize Git in the surrounding WorkBuddy workspace.
- Never track virtual environments, media, subtitles, `.env` files, cookies, tokens, model caches, local outputs, or user MCP configuration.
- Pin core dependencies to mcp 1.28.1, yt-dlp 2026.7.4, and playwright 1.61.0; pin optional faster-whisper to 1.2.1.
- Python 3.10–3.13 are supported; every test stays offline and credential-free.
- The public WeChat Worker is called only when `WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER=true` (case-insensitive) is set explicitly.
- An explicitly configured custom `WECHAT_CHANNELS_WORKER_URL` is considered user opt-in.

---

### Task 0: Initialize the independent local repository

**Files:**
- Create: `.git/` metadata only inside `video-link-mcp/`

**Interfaces:**
- Produces a local `main` branch for task-level commits. It does not create a remote or transmit any file.

- [ ] **Step 1: Initialize Git locally**

Run only from `video-link-mcp/`:

```powershell
git init
git branch -M main
git status --short --ignored
```

Expected: Git reports a new local repository. Do not run `git remote add` or `git push`.

---

### Task 1: Establish the private-repository boundary

**Files:**
- Modify: `.gitignore`
- Create: `.env.example`, `SECURITY.md`, `LICENSE`, `CHANGELOG.md`
- Create: `tests/test_repository_hygiene.py`

**Interfaces:**
- Produces an ignore policy and safe configuration templates used by every later task.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Verify RED**

Run: `venv\\Scripts\\python.exe -m unittest tests.test_repository_hygiene -v`

Expected: FAIL because `tests/` and `.env.example` do not exist.

- [ ] **Step 3: Implement the repository boundary**

Append this to `.gitignore`:

```gitignore
# Local configuration and credentials
.env
.env.*
!.env.example
*.pem
*.key
*.token

# Local application output
outputs/
downloads/
.playwright/
```

Create `.env.example`:

```dotenv
WECHAT_CHANNELS_YUANBAO_COOKIE=
WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER=false
WECHAT_CHANNELS_WORKER_URL=
PIP_INDEX_URL=
```

Create `SECURITY.md` that forbids committing browser/Yuanbao cookies, `cookies.txt`, `.env`, media, and debug captures. Create `LICENSE` with an internal-use/no-redistribution notice. Create `CHANGELOG.md` with an `Unreleased` section and one initial private-distribution entry.

- [ ] **Step 4: Verify GREEN**

Run: `venv\\Scripts\\python.exe -m unittest tests.test_repository_hygiene -v`

Expected: PASS, 2 tests.

### Task 2: Require explicit consent for the public WeChat Worker

**Files:**
- Modify: `lib/wechat_channels_api.py`
- Create: `tests/test_wechat_channels_api.py`

**Interfaces:**
- Produces `is_public_worker_allowed() -> bool`, `is_custom_worker_configured() -> bool`, and a `parse_share_link()` path that never sends an unapproved public-Worker request.

- [ ] **Step 1: Write the failing privacy tests**

```python
import os
import unittest
from unittest.mock import patch
from lib import wechat_channels_api as api

class WorkerPrivacyTests(unittest.TestCase):
    def test_public_worker_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(api, '_parse_share_url_worker') as worker:
                self.assertIsNone(api.parse_share_link('https://weixin.qq.com/sph/example'))
        worker.assert_not_called()

    def test_public_worker_requires_true_flag(self):
        env = {'WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER': 'true'}
        with patch.dict(os.environ, env, clear=True):
            with patch.object(api, '_parse_share_url_worker', return_value={'feedInfo': {}}) as worker:
                self.assertEqual(api.parse_share_link('https://weixin.qq.com/sph/example'), {'feedInfo': {}})
        worker.assert_called_once()

    def test_custom_worker_is_explicit_opt_in(self):
        env = {'WECHAT_CHANNELS_WORKER_URL': 'https://worker.example/api'}
        with patch.dict(os.environ, env, clear=True):
            with patch.object(api, '_parse_share_url_worker', return_value={'feedInfo': {}}) as worker:
                self.assertEqual(api.parse_share_link('https://weixin.qq.com/sph/example'), {'feedInfo': {}})
        worker.assert_called_once()
```

- [ ] **Step 2: Verify RED**

Run: `venv\\Scripts\\python.exe -m unittest tests.test_wechat_channels_api -v`

Expected: the default test FAILS because the existing code calls the Worker.

- [ ] **Step 3: Implement the minimal privacy gate**

Add these helpers:

```python
def is_custom_worker_configured() -> bool:
    return bool(os.environ.get('WECHAT_CHANNELS_WORKER_URL', '').strip())

def is_public_worker_allowed() -> bool:
    value = os.environ.get('WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER', '')
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}

def is_worker_allowed() -> bool:
    return is_custom_worker_configured() or is_public_worker_allowed()
```

Replace the final Worker fallback in `parse_share_link()` with:

```python
if not is_worker_allowed():
    print('[wechat_channels_api] Worker fallback disabled; configure a Yuanbao cookie, custom Worker URL, or explicit public-Worker opt-in.')
    return None
return _parse_share_url_worker(share_url, timeout)
```

Update the no-cookie/no-opt-in errors in `download_video()` and `get_video_info()` to say exactly: `Worker fallback is disabled. Configure WECHAT_CHANNELS_YUANBAO_COOKIE, WECHAT_CHANNELS_WORKER_URL, or WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER=true.` Never echo cookie values.

- [ ] **Step 4: Verify GREEN**

Run: `venv\\Scripts\\python.exe -m unittest tests.test_wechat_channels_api -v`

Expected: PASS, 3 tests, without network access.

### Task 3: Add an offline diagnostics command

**Files:**
- Create: `diagnose.py`
- Create: `tests/test_diagnose.py`
- Modify: `test_server.py`

**Interfaces:**
- Produces `collect_diagnostics() -> dict` and `python diagnose.py --json`.

- [ ] **Step 1: Write the failing test**

```python
import unittest
from unittest.mock import patch
import diagnose

class DiagnoseTests(unittest.TestCase):
    def test_collect_diagnostics_reports_all_capabilities(self):
        result = diagnose.collect_diagnostics()
        for name in ('python', 'core_dependencies', 'ffmpeg', 'playwright_browser', 'speech_to_text', 'core_ready'):
            self.assertIn(name, result)

    @patch('diagnose.importlib.util.find_spec', return_value=None)
    def test_core_ready_is_false_when_a_required_package_is_missing(self, _):
        self.assertFalse(diagnose.collect_diagnostics()['core_ready'])
```

- [ ] **Step 2: Verify RED**

Run: `venv\\Scripts\\python.exe -m unittest tests.test_diagnose -v`

Expected: FAIL because `diagnose.py` does not exist.

- [ ] **Step 3: Implement diagnostics**

Implement `collect_diagnostics()` with this exact result shape:

```python
{
    'python': sys.version.split()[0],
    'supported_python': (3, 10) <= sys.version_info[:2] <= (3, 13),
    'core_dependencies': {'mcp': bool, 'yt_dlp': bool, 'playwright': bool},
    'ffmpeg': bool,
    'playwright_browser': bool,
    'speech_to_text': bool,
    'core_ready': bool,
}
```

Use `importlib.util.find_spec` for package checks and `shutil.which('ffmpeg')` for ffmpeg. The browser check must stay offline: inspect Playwright's installed executable path and return false if unavailable; do not install anything. Add `--json`; plain output prints one check per line. Exit 0 only when `core_ready` is true. Add an import-only smoke check to `test_server.py`.

- [ ] **Step 4: Verify GREEN**

Run:
```powershell
venv\\Scripts\\python.exe -m unittest tests.test_diagnose -v
venv\\Scripts\\python.exe diagnose.py --json
```

Expected: tests PASS and the command prints valid JSON.

### Task 4: Make installation repeatable on all target systems

**Files:**
- Modify: `requirements.txt`, `requirements-stt.txt`, `setup.bat`
- Create: `setup.sh`, `tests/test_setup_scripts.py`

**Interfaces:**
- Consumes: Python 3.10–3.13, optional `PIP_INDEX_URL`, optional `--with-stt`.
- Produces: a local virtual environment, installed core packages/Chromium, test output, diagnostic output, and a current-machine MCP configuration snippet.

- [ ] **Step 1: Write failing setup-contract tests**

```python
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
        self.assertIn('python -m venv', script)
```

- [ ] **Step 2: Verify RED**

Run: `venv\\Scripts\\python.exe -m unittest tests.test_setup_scripts -v`

Expected: FAIL because `setup.sh` is absent and the Windows script hard-codes a mirror.

- [ ] **Step 3: Implement pinned dependencies and setup scripts**

Set `requirements.txt` exactly to:

```text
mcp==1.28.1
yt-dlp==2026.7.4
playwright==1.61.0
```

Set `requirements-stt.txt` exactly to:

```text
faster-whisper==1.2.1
```

Rewrite `setup.bat` to validate Python 3.10–3.13, create/reuse `venv`, use normal pip invocation without a hard-coded `-i`, install Chromium, process `--with-stt`, run `test_server.py` and `diagnose.py`, print MCP configuration using `%PROJECT_DIR%`, and exit non-zero on a required failure. Remove `pause`.

Create executable `setup.sh` using `set -euo pipefail`, `python3`/ `PYTHON_BIN`, the same version check, `venv/bin/python`, `playwright install chromium`, an optional `--with-stt` block, then `test_server.py` and `diagnose.py`. Do not override `PIP_INDEX_URL`; pip will honor it when the caller sets it.

- [ ] **Step 4: Verify GREEN**

Run:
```powershell
venv\\Scripts\\python.exe -m unittest tests.test_setup_scripts -v
cmd /c setup.bat
```

Expected: contract tests PASS; setup exits 0 and runs the test and diagnostic commands.

### Task 5: Document private GitHub onboarding

**Files:**
- Modify: `README.md`, `mcp_config_example.json`
- Create: `docs/private-github-setup.md`
- Modify: `tests/test_repository_hygiene.py`

**Interfaces:**
- Produces copyable installation, update, diagnostics, and privacy instructions.

- [ ] **Step 1: Add this failing README contract**

```python
def test_readme_documents_private_installation_and_worker_opt_in(self):
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    for text in ('git clone', 'setup.bat', 'setup.sh', 'diagnose.py', 'WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER'):
        self.assertIn(text, readme)
```

- [ ] **Step 2: Verify RED**

Run: `venv\\Scripts\\python.exe -m unittest tests.test_repository_hygiene -v`

Expected: FAIL because the README lacks the private GitHub installation path and opt-in variable.

- [ ] **Step 3: Update docs and configuration**

Document clone → setup → ffmpeg → MCP config → diagnostics → `git pull` updates. Document `--with-stt`, per-computer Cookies, the explicit public Worker opt-in, and a self-hosted Worker alternative. Replace any wording that says the public Worker is automatic or out-of-box.

Set the example environment section to:

```json
"env": {
  "WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER": "false"
}
```

Create `docs/private-github-setup.md` with pre-push checks and recovery commands for missing Python, ffmpeg, Chromium, and STT.

- [ ] **Step 4: Verify GREEN**

Run: `venv\\Scripts\\python.exe -m unittest tests.test_repository_hygiene -v`

Expected: PASS, 3 tests.

### Task 6: Add GitHub Actions to the independent repository

**Files:**
- Create: `.github/workflows/test.yml`
- Create: `tests/test_ci_workflow.py`

**Interfaces:**
- Produces an offline test workflow for every push and pull request.

- [ ] **Step 1: Write the failing workflow-contract test**

```python
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]

class CiWorkflowTests(unittest.TestCase):
    def test_workflow_runs_offline_unittest_suite(self):
        workflow = (ROOT / '.github/workflows/test.yml').read_text(encoding='utf-8')
        self.assertIn('python -m unittest discover -s tests -v', workflow)
        self.assertIn('actions/setup-python', workflow)
        self.assertNotIn('WECHAT_CHANNELS_YUANBAO_COOKIE', workflow)
```

- [ ] **Step 2: Verify RED**

Run: `venv\\Scripts\\python.exe -m unittest tests.test_ci_workflow -v`

Expected: FAIL because the workflow is absent.

- [ ] **Step 3: Implement CI and initialize Git**

Create this workflow:

```yaml
name: Offline tests
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.10', '3.13']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pip install --upgrade pip
      - run: python -m pip install -r requirements.txt
      - run: python -m unittest discover -s tests -v
```

Then run only inside `video-link-mcp/`:

```powershell
git init
git branch -M main
git check-ignore -v venv outputs .env cookies.txt
git add .
git status --short
```

Inspect all staged names; remove any local file that bypassed ignore rules. Do not add a remote or push.

- [ ] **Step 4: Verify GREEN and create the initial local commit**

Run:
```powershell
venv\\Scripts\\python.exe -m unittest discover -s tests -v
venv\\Scripts\\python.exe test_server.py
venv\\Scripts\\python.exe diagnose.py --json
git diff --cached --check
git ls-files | Select-String -Pattern '(^|/)(venv|outputs|downloads|__pycache__)/|\\.env$|cookies|\\.(mp4|mkv|webm|vtt|srt|wav|pem|key|token)$'
git commit -m "feat: prepare private GitHub distribution"
```

Expected: all tests PASS; diagnostics return JSON; staged diff has no whitespace errors; the secret/artifact scan produces no output; the commit succeeds.

### Task 7: Hand off for private GitHub publishing

**Files:**
- Verify: all repository files.

- [ ] **Step 1: Re-run the final evidence set**

Run:
```powershell
venv\\Scripts\\python.exe -m unittest discover -s tests -v
git status --short
git log --oneline -3
```

Expected: all tests PASS and the working tree is clean.

- [ ] **Step 2: Publish only after the user provides the private repository URL**

```powershell
git remote add origin <private-repository-url>
git push -u origin main
```

Do not create a remote or push without the user’s explicit request and target URL.
