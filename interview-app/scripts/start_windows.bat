@echo off
chcp 65001 > nul
rem ===== リアルタイムAI面接支援 起動 (Windows) =====
cd /d %~dp0\..
call .venv\Scripts\activate.bat
echo Ollama が起動していない場合は別ウィンドウで起動します...
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL || start "Ollama" /min ollama serve
echo サーバーを起動します: http://localhost:8765
echo スマホからは、画面に表示されるQRコードで接続してください（同一Wi-Fi内）。
start "" http://localhost:8765
python -m uvicorn app.main:app --host 0.0.0.0 --port 8765
pause
