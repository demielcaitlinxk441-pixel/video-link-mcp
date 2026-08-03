@echo off
setlocal
set "ROOT=%~dp0.."
set "PATH=%ROOT%\venv\Scripts;%PATH%"
for /f "usebackq delims=" %%K in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('AGNES_API_KEY','User')"`) do set "AGNES_API_KEY=%%K"
for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('AGNES_API_BASE_URL','User')"`) do set "AGNES_API_BASE_URL=%%U"
for /f "usebackq delims=" %%M in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('AGNES_MODEL','User')"`) do set "AGNES_MODEL=%%M"
set "PYTHON=%ROOT%\venv\Scripts\pythonw.exe"
if not exist "%PYTHON%" set "PYTHON=%ROOT%\venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=%LOCALAPPDATA%\VideoLinkAnalyzer\runtime\Scripts\pythonw.exe"
if not exist "%PYTHON%" set "PYTHON=%LOCALAPPDATA%\VideoLinkAnalyzer\runtime\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo Virtual environment not found. Run setup.bat first.
  pause
  exit /b 1
)

start "视频下载" /b "%PYTHON%" "%ROOT%\desktop_app.py"
