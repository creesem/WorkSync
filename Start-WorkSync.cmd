@echo off
setlocal
set "ROOT=%~dp0"
set "GUI=%ROOT%.venv\Scripts\worksync-gui.exe"

if not exist "%GUI%" (
  echo The virtual environment is missing. Run Bootstrap.cmd first.
  exit /b 1
)

start "" "%GUI%"
