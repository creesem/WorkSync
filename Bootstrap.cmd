@echo off
setlocal
set "ROOT=%~dp0"
set "WHEELS=%ROOT%wheels"
set "PY=%ROOT%.venv\Scripts\python.exe"

if not exist "%WHEELS%\worksync-*.whl" (
  echo Building the worksync wheel into "%WHEELS%" ...
  py -3 -m pip wheel "%ROOT%." -w "%WHEELS%" || goto :error
)

if not exist "%PY%" (
  echo Creating virtual environment at "%ROOT%.venv" ...
  py -3 -m venv "%ROOT%.venv" || goto :error
)

"%PY%" -m pip install --upgrade pip || goto :error

echo Installing from local wheels ...
"%PY%" -m pip install --no-index --find-links "%WHEELS%" worksync || goto :error

echo.
echo Installed. Configure then run:
echo   copy config\worksync.example.json config\worksync.json
echo   .venv\Scripts\worksync --help
exit /b 0

:error
echo Bootstrap failed with error %errorlevel%.
exit /b %errorlevel%
