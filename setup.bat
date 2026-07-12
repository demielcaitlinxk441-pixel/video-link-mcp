@echo off
chcp 65001 >nul 2>nul
setlocal

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "WITH_STT=false"
if /I "%~1"=="--with-stt" set "WITH_STT=true"

echo Video Link Analyzer MCP Server setup
echo.

python -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)"
if errorlevel 1 (
    echo ERROR: Python 3.10 through 3.13 is required and must be in PATH.
    exit /b 1
)

if not exist "%PROJECT_DIR%\venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv "%PROJECT_DIR%\venv"
    if errorlevel 1 exit /b 1
)

set "PYTHON=%PROJECT_DIR%\venv\Scripts\python.exe"
echo Installing core dependencies...
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
"%PYTHON%" -m pip install -r "%PROJECT_DIR%\requirements.txt"
if errorlevel 1 exit /b 1

echo Installing Playwright Chromium...
"%PYTHON%" -m playwright install chromium
if errorlevel 1 (
    echo ERROR: Playwright Chromium installation failed.
    exit /b 1
)

if /I "%WITH_STT%"=="true" (
    echo Installing optional speech-to-text dependencies...
    "%PYTHON%" -m pip install -r "%PROJECT_DIR%\requirements-stt.txt"
    if errorlevel 1 exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo WARNING: ffmpeg was not found. Video merging and transcription need it.
    echo Install it with: winget install ffmpeg
) else (
    echo ffmpeg found.
)

echo Running offline checks...
"%PYTHON%" "%PROJECT_DIR%\test_server.py"
if errorlevel 1 exit /b 1
"%PYTHON%" "%PROJECT_DIR%\diagnose.py"
if errorlevel 1 exit /b 1

echo.
echo Add this entry to your MCP client configuration:
echo {
echo   "mcpServers": {
echo     "video-link-analyzer": {
echo       "command": "%PROJECT_DIR%\venv\Scripts\python.exe",
echo       "args": ["%PROJECT_DIR%\server.py"]
echo     }
echo   }
echo }
echo.
echo Optional speech-to-text: setup.bat --with-stt
