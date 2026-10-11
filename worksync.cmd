@echo off
setlocal
set "ROOT=%~dp0"
set "CLI=%ROOT%.venv\Scripts\worksync.exe"

if not exist "%CLI%" (
  echo The virtual environment is missing. Run Bootstrap.cmd first.
  exit /b 1
)

"%CLI%" %*
