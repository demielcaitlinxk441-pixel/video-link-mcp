@echo off
setlocal
set "ROOT=%~dp0.."
set "PYTHON=%ROOT%\venv\Scripts\pythonw.exe"
if not exist "%PYTHON%" set "PYTHON=%ROOT%\venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo Virtual environment not found. Run setup.bat first.
  pause
  exit /b 1
)

start "Video Link Analyzer" /b "%PYTHON%" "%ROOT%\desktop_app.py"
