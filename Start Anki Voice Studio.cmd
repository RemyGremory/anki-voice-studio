@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Python environment is missing. Ask the person who sent you this folder to run the setup first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -c "import omnivoice, lameenc" >nul 2>nul
if errorlevel 1 (
  echo The audio engine is not ready yet. Run setup_and_start.cmd once while connected to the internet.
  pause
  exit /b 1
)

start "Anki Voice Studio" /min ".venv\Scripts\python.exe" anki_voice_server.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8766
