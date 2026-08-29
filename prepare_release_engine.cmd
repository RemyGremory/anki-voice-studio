@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "EDITION=%~1"
if "%EDITION%"=="" set "EDITION=cpu"

if /I "%EDITION%"=="cpu" (
  set "BUILD_ENV=.venv-cpu"
  set "REQUIREMENTS=requirements-cpu.txt"
  set "TORCH_INDEX=https://download.pytorch.org/whl/cpu"
) else if /I "%EDITION%"=="nvidia" (
  set "BUILD_ENV=.venv-nvidia"
  set "REQUIREMENTS=requirements-nvidia.txt"
  set "TORCH_INDEX=https://download.pytorch.org/whl/cu128"
) else (
  echo Choose an edition: cpu or nvidia.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo The development environment .venv is required to prepare a release build.
  exit /b 1
)

if not exist "%BUILD_ENV%\Scripts\python.exe" ".venv\Scripts\python.exe" -m venv "%BUILD_ENV%"

echo Installing the %EDITION% release engine. This can download several gigabytes.
"%BUILD_ENV%\Scripts\python.exe" -m pip install --upgrade pip
"%BUILD_ENV%\Scripts\python.exe" -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url "%TORCH_INDEX%"
"%BUILD_ENV%\Scripts\python.exe" -m pip install -r "%REQUIREMENTS%"
"%BUILD_ENV%\Scripts\python.exe" -m pip install pyinstaller

if errorlevel 1 (
  echo.
  echo Release environment preparation did not finish.
  exit /b 1
)

echo Ready: %BUILD_ENV%
