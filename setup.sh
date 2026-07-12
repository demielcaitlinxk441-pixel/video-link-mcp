#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
WITH_STT="${1:-}"

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)'
"$PYTHON_BIN" -m venv "$PROJECT_DIR/venv"

PYTHON="$PROJECT_DIR/venv/bin/python"
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt"
"$PYTHON" -m playwright install chromium

if [[ "$WITH_STT" == "--with-stt" ]]; then
  "$PYTHON" -m pip install -r "$PROJECT_DIR/requirements-stt.txt"
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "WARNING: ffmpeg was not found. Video merging and transcription need it."
fi

"$PYTHON" "$PROJECT_DIR/test_server.py"
"$PYTHON" "$PROJECT_DIR/diagnose.py"

cat <<EOF
Add this entry to your MCP client configuration:
{
  "mcpServers": {
    "video-link-analyzer": {
      "command": "$PROJECT_DIR/venv/bin/python",
      "args": ["$PROJECT_DIR/server.py"]
    }
  }
}
EOF
