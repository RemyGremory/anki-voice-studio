@echo off
setlocal
cd /d "%~dp0"

echo This legacy command creates the NVIDIA release edition.
echo For the compact build, use build_release.cmd cpu.
call build_release.cmd nvidia
pause
