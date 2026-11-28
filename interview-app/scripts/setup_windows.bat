@echo off
chcp 65001 > nul
rem ===== リアルタイムAI面接支援 初回セットアップ (Windows) =====
cd /d %~dp0\..
where python > nul 2>&1 || (echo Python 3.11+ が見つかりません。https://www.python.org からインストールしてください。 & pause & exit /b 1)
if not exist .venv (
  echo 仮想環境を作成します...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install PyAudioWPatch
echo.
echo Whisperモデル(base)を事前にダウンロードします（初回のみネット接続が必要）...
python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8'); print('whisper base OK')"
echo.
echo ===== セットアップ完了 =====
echo Ollama（生成AI）を使う場合は docs\MODELS.md の手順でインストールし、
echo モデルを取得してください:  ollama pull qwen2.5:7b-instruct-q4_K_M
echo 起動は scripts\start_windows.bat から行えます。
pause
