@echo off
setlocal
set "ROOT=%~dp0"
set "GUI=%ROOT%.venv\Scripts\worksync-gui.exe"
set "UI=%WORKSYNC_UI_DIR%"
if "%UI%"=="" set "UI=%ROOT%..\worksync-ui"

if not exist "%GUI%" (
  echo The virtual environment is missing. Run Bootstrap.cmd first.
  exit /b 1
)
if not exist "%UI%\index.html" (
  echo The worksync-ui checkout was not found at "%UI%". Set WORKSYNC_UI_DIR to override.
  exit /b 1
)

start "" "%GUI%" --ui-dir "%UI%"
