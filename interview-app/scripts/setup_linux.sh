#!/bin/sh
# 開発/検証環境用セットアップ (Linux)
set -e
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt soundfile pytest
.venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8'); print('whisper base OK')"
echo "setup done: ./scripts/start_linux.sh"
