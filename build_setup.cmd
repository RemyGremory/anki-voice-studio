@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\pyinstaller.exe" (
  echo The development build environment is missing.
  exit /b 1
)

echo Creating the small Anki Voice Studio setup launcher.
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed --name "AnkiVoiceStudioSetup" ^
  --add-data "bootstrap_manifest.json;." ^
  --add-data "setup_web;setup_web" ^
  anki_voice_setup.py

if errorlevel 1 (
  echo Setup launcher build did not finish.
  exit /b 1
)

echo Ready: dist\AnkiVoiceStudioSetup.exe
