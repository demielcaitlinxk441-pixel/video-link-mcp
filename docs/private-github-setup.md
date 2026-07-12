# Private GitHub setup

## Before pushing

- Run `git status --short` and verify no downloaded media, Cookies, `.env`, or `venv` files are present.
- Run `venv\Scripts\python.exe -m unittest discover -s tests -v` on Windows, or `venv/bin/python -m unittest discover -s tests -v` on macOS/Linux.
- Keep the repository private; its internal-use license does not grant public redistribution rights.

## Fresh computer

Clone the private repository, then run `setup.bat` on Windows or `chmod +x setup.sh && ./setup.sh` on macOS/Linux. Add `--with-stt` if automatic transcription is needed. The script prints the exact MCP configuration for that computer.

## Recovery

- Python missing: install Python 3.10–3.13 and ensure `python` (Windows) or `python3` (macOS/Linux) is on PATH.
- ffmpeg missing: install it through the system package manager, then run `diagnose.py` again.
- Chromium missing: run `venv\Scripts\python.exe -m playwright install chromium` on Windows, or `venv/bin/python -m playwright install chromium` on macOS/Linux.
- Speech-to-text missing: rerun the setup script with `--with-stt`.

## Credentials and video号 privacy

Each computer manages its own browser login and optional `WECHAT_CHANNELS_YUANBAO_COOKIE`. The default public Worker is disabled. To use it deliberately, set `WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER=true`; alternatively, set a self-hosted `WECHAT_CHANNELS_WORKER_URL`.
