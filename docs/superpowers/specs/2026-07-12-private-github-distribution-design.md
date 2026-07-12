# Private GitHub Distribution Design

## Goal

Make Video Link Analyzer MCP safe and repeatable to install from a private GitHub repository on another computer, without committing machine-specific environments, media, browser credentials, or service cookies.

## Scope

The repository supports Windows, macOS, and Linux installation from source. Each machine creates its own virtual environment, installs its own browser runtime, and stores its own credentials outside version control.

The project remains a local stdio MCP server. It does not add a hosted API, Docker deployment, user accounts, or binary releases.

## Repository Boundary

The Git repository root is `video-link-mcp/`, not the surrounding WorkBuddy workspace. Tracked files are source code, tests, dependency definitions, setup scripts, configuration templates, and documentation.

The following are never tracked: `venv/`, Python caches, downloaded media, subtitle files, diagnostic output, model caches, `.env` files, private keys, tokens, browser cookies, and local MCP configuration files.

## Installation Design

`setup.bat` is the Windows entrypoint. A new `setup.sh` provides the same flow for macOS and Linux.

Both scripts will:

1. Validate a supported Python version.
2. Create or reuse a project-local virtual environment.
3. Install the pinned core dependency set.
4. Install the Playwright Chromium runtime.
5. Detect ffmpeg and clearly state which features need it.
6. Optionally install speech-to-text dependencies when requested.
7. Run the offline test suite.
8. Print the exact MCP configuration for the current machine.

The default package index is PyPI. A caller may override it with `PIP_INDEX_URL`; no regional mirror is hard-coded.

## Configuration and Secrets

`.env.example` documents optional configuration names only. The server will load no implicit secret file in this change; clients pass optional values through their MCP environment configuration. This avoids changing the existing execution model while still providing a safe template.

`WECHAT_CHANNELS_WORKER_URL` is no longer assumed for privacy-sensitive operation. The public Worker fallback must require explicit opt-in through `WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER=true`. Without a Yuanbao cookie or that opt-in, a WeChat Channels request returns a clear configuration error without sending the link to the public Worker.

Cookies and tokens are never echoed in server responses or written to repository-controlled files.

## Dependency and Compatibility Policy

Core dependencies are pinned to tested versions in `requirements.txt`. Speech-to-text remains optional in `requirements-stt.txt` and is pinned separately. Python 3.10 through 3.13 are supported.

ffmpeg is an external prerequisite: downloads can proceed where possible without it, but merged video output and audio extraction/transcription require it. The scripts do not install an operating-system package manager dependency automatically.

## Diagnostics and Testing

`test_server.py` remains an offline smoke test. A new diagnostic command verifies the Python runtime, packages, Playwright browser availability, ffmpeg, and optional speech-to-text installation without downloading real content.

GitHub Actions runs the offline test suite on each push and pull request. The workflow must not use real platform URLs, cookies, or secrets.

## Documentation

The README will provide a short private-repository onboarding path: clone, run setup, install ffmpeg if needed, add the printed MCP configuration, and run diagnostics. It will document the credential boundary, external-service opt-in, platform limitations, and update flow (`git pull`, then re-run setup/diagnostics).

`SECURITY.md` states how to report vulnerabilities and lists data that must never be committed. `CHANGELOG.md` records user-visible releases. An internal-use license notice clarifies that the private repository is not published as open-source software.

## Error Handling

Installation and diagnostic failures exit non-zero and show a direct recovery command. Missing optional capabilities do not block base link detection and metadata features. A disabled public Worker fallback reports the exact environment variable needed to enable it.

## Acceptance Criteria

- A fresh Windows, macOS, or Linux machine can clone the private repository, run the platform setup script, and receive a working MCP configuration without copying `venv/`.
- The repository refuses to stage common secret, media, cache, and local-output files through ignore rules and documents this boundary.
- The public WeChat Worker is never contacted unless its opt-in environment variable is explicitly set.
- The offline test suite and diagnostic command are runnable after setup.
- GitHub Actions verifies the offline suite without platform credentials.
