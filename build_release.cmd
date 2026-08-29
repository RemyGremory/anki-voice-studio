@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "EDITION=%~1"
if "%EDITION%"=="" set "EDITION=cpu"

if /I "%EDITION%"=="cpu" (
  set "BUILD_ENV=.venv-cpu"
  set "RELEASE_NAME=AnkiVoiceStudio-CPU"
) else if /I "%EDITION%"=="nvidia" (
  set "BUILD_ENV=.venv-nvidia"
  if not exist "%BUILD_ENV%\Scripts\python.exe" set "BUILD_ENV=.venv"
  set "RELEASE_NAME=AnkiVoiceStudio-NVIDIA"
) else (
  echo Choose an edition: cpu or nvidia.
  exit /b 1
)

if not exist "%BUILD_ENV%\Scripts\pyinstaller.exe" (
  echo Build environment %BUILD_ENV% is not ready yet.
  echo This is a developer-only step. Do not send this script to users.
  exit /b 1
)

echo Creating %RELEASE_NAME% without personal profiles, recordings, or the OmniVoice model.
"%BUILD_ENV%\Scripts\pyinstaller.exe" --noconfirm --clean --onedir --noconsole --name "%RELEASE_NAME%" ^
  --add-data "web;web" ^
  --add-data "component_manifest.json;." ^
  --add-data "../anki_audio_drag_helper;anki_audio_drag_helper" ^
  --collect-all omnivoice ^
  --collect-all transformers ^
  --collect-all torchaudio ^
  --collect-all librosa ^
  --collect-all soundfile ^
  --collect-all imageio_ffmpeg ^
  --collect-all pydub ^
  --hidden-import lameenc ^
  --hidden-import torch ^
  --hidden-import numpy ^
  anki_voice_server.py

if errorlevel 1 (
  echo.
  echo Build did not finish. See the text above for details.
  exit /b 1
)

echo.
echo Ready: dist\%RELEASE_NAME%\%RELEASE_NAME%.exe
echo The OmniVoice model is intentionally not inside this folder.
echo Next, split this folder with prepare_release_assets.py and add its checksums to the release manifest.
