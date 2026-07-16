@echo off
setlocal

set "PROJECT_DIR=%~dp0.."
set "PYTHON=%PROJECT_DIR%\venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=%LOCALAPPDATA%\VideoLinkAnalyzer\runtime\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo ERROR: Run setup.bat first.
    exit /b 1
)

"%PYTHON%" "%PROJECT_DIR%\server.py" --transport http %*
