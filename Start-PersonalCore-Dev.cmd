@echo off
setlocal
rem Personal-core dev lane. The daily app stays on main (port 8765).
rem Engine and shell are isolated worktrees; runtime is separate from the daily var.
set "REPO=%~dp0"
set "ENGINE=C:\Users\macre\.local\share\opencode\worktree\6c859b\personal-core"
set "SHELL=B:\GitHubProjects\worksync-ui-personal"
set "PYTHON=%REPO%.venv\Scripts\python.exe"
set "PYTHONPATH=%ENGINE%\src"
set "WORKSYNC_CONFIG=%REPO%config\worksync.json"
set "VAULT=B:/ObsidianNotes/WorkSync"
set "RUNTIME=%ENGINE%\var-personal-dev"

"%PYTHON%" -m worksync.gui.main --vault "%VAULT%" --runtime "%RUNTIME%" --port 8766 --ui-dir "%SHELL%" --no-browser
