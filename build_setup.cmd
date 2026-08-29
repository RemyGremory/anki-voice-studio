@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\pyinstaller.exe" (
  echo The development build environment is missing.
  exit /b 1
)

if not exist "build\specs" mkdir "build\specs"

echo Creating the small Anki Voice Studio setup launcher.
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed --name "AnkiVoiceStudioSetup" ^
  --specpath "build\specs" ^
  --icon "%CD%\setup_web\assets\anki-voice-studio.ico" ^
  --add-data "%CD%\bootstrap_manifest.json;." ^
  --add-data "%CD%\setup_web;setup_web" ^
  --collect-data certifi ^
  anki_voice_setup.py

if errorlevel 1 (
  echo Setup launcher build did not finish.
  exit /b 1
)

echo Ready: dist\AnkiVoiceStudioSetup.exe
