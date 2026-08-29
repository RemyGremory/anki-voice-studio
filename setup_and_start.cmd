@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Python environment is missing. Ask the person who sent you this folder to run the setup first.
  pause
  exit /b 1
)

echo Installing the local audio engine. This may take a while the first time.
".venv\Scripts\python.exe" -m pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 (
  echo.
  echo Setup did not finish. Check the internet connection and try again.
  pause
  exit /b 1
)

call "Start Anki Voice Studio.cmd"
