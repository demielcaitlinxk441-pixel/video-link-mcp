@echo off
chcp 65001 >nul 2>nul
setlocal EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "WITH_STT=false"
if /I "%~1"=="--with-stt" set "WITH_STT=true"

echo Video Link Analyzer MCP Server setup
echo.

call :locate_python
if not defined BASE_PYTHON (
    echo Python 3.10 through 3.13 was not found. Installing Python 3.13...
    call :install_python
    if errorlevel 1 exit /b 1
    call :locate_python
)
if not defined BASE_PYTHON (
    echo ERROR: Python installation finished, but Python could not be located.
    exit /b 1
)

set "VENV_DIR=%PROJECT_DIR%\venv"
if not exist "%VENV_DIR%\Scripts\python.exe" (
    for /f %%L in ('powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('PROJECT_DIR').Length"') do set "PROJECT_PATH_LENGTH=%%L"
    if !PROJECT_PATH_LENGTH! GTR 80 (
        set "VENV_DIR=%LOCALAPPDATA%\VideoLinkAnalyzer\runtime"
        echo Project path is long. Using a short local runtime directory instead.
    )
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment...
    "%BASE_PYTHON%" -m venv "%VENV_DIR%"
    if errorlevel 1 exit /b 1
)

set "PYTHON=%VENV_DIR%\Scripts\python.exe"
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

echo Checking or installing ffmpeg...
set "FFMPEG_EXE="
for /f "delims=" %%F in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\ensure_ffmpeg.ps1"') do set "FFMPEG_EXE=%%F"
if errorlevel 1 exit /b 1
if not defined FFMPEG_EXE (
    echo ERROR: ffmpeg installation did not return an executable path.
    exit /b 1
)
for %%F in ("%FFMPEG_EXE%") do set "PATH=%%~dpF;%PATH%"
echo ffmpeg found.

echo Running offline checks...
"%PYTHON%" "%PROJECT_DIR%\scripts\verify.py"
if errorlevel 1 exit /b 1
"%PYTHON%" "%PROJECT_DIR%\diagnose.py"
if errorlevel 1 exit /b 1

echo Creating desktop shortcut...
if /I "%VIDEO_LINK_SKIP_SHORTCUT%"=="1" (
    echo Skipping desktop shortcut creation for this automated setup check.
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_DIR%\scripts\create_desktop_shortcut.ps1" -ProjectRoot "%PROJECT_DIR%"
    if errorlevel 1 (
        echo WARNING: The desktop shortcut could not be created. You can run scripts\start_desktop_app.bat directly.
    )
)

echo.
echo Add this entry to your MCP client configuration:
echo {
echo   "mcpServers": {
echo     "video-link-analyzer": {
echo       "command": "%PYTHON%",
echo       "args": ["%PROJECT_DIR%\server.py"]
echo     }
echo   }
echo }
echo.
echo For compatible HTTP MCP clients, start the local service with:
echo   scripts\start_http_mcp.bat
echo Then use this URL in that client: http://127.0.0.1:8000/mcp
echo Use scripts\start_http_mcp.bat --port 8765 if port 8000 is occupied.
echo.
echo To use the desktop downloader, double-click "Video Link Analyzer" on your desktop.
echo.
echo Optional speech-to-text: setup.bat --with-stt
goto :eof

:locate_python
set "BASE_PYTHON="
for %%V in (3.13 3.12 3.11 3.10) do (
    for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do (
        if not defined BASE_PYTHON set "BASE_PYTHON=%%P"
    )
)
if not defined BASE_PYTHON (
    for %%P in ("%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "%ProgramFiles%\Python313\python.exe") do (
        if not defined BASE_PYTHON if exist "%%~fP" set "BASE_PYTHON=%%~fP"
    )
)
if not defined BASE_PYTHON (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined BASE_PYTHON (
            "%%P" -c "import sys; raise SystemExit(0 if (3, 10) ^<= sys.version_info[:2] ^<= (3, 13) else 1)" >nul 2>nul && set "BASE_PYTHON=%%P"
        )
    )
)
exit /b 0

:install_python
where winget >nul 2>nul
if errorlevel 1 (
    echo ERROR: Windows App Installer (winget) is required to install Python automatically.
    exit /b 1
)
winget install --id Python.Python.3.13 --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
exit /b %errorlevel%
