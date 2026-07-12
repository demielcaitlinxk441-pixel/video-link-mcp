@echo off
chcp 65001 >nul
setlocal

:: download_with_cookies.bat
:: 使用浏览器 Cookie 下载视频（解决抖音 "Fresh cookies needed" 等问题）
:: 用法：download_with_cookies.bat <URL> [chrome|edge|firefox] [输出目录]

set "URL=%~1"
set "BROWSER=%~2"
set "OUTDIR=%~3"

if "%URL%"=="" (
    echo 用法：download_with_cookies.bat ^<URL^> [chrome^|edge^|firefox] [输出目录]
    echo 示例：download_with_cookies.bat https://www.douyin.com/video/123456789 chrome
    exit /b 1
)

if "%BROWSER%"=="" set "BROWSER=chrome"
if "%OUTDIR%"=="" set "OUTDIR=%TEMP%\video-link-analyzer"

set "PYTHON=%~dp0..\venv\Scripts\python.exe"
set "SCRIPT=%~dp0download_direct.py"

if not exist "%PYTHON%" (
    echo 错误：未找到 venv\Scripts\python.exe
    echo 请先运行 setup.bat 安装依赖。
    exit /b 1
)

echo 正在使用 %BROWSER% 的 Cookie 下载视频：%URL%
"%PYTHON%" "%SCRIPT%" "%URL%" "%BROWSER%" "%OUTDIR%"
if %ERRORLEVEL% neq 0 (
    echo.
    echo 下载失败。常见原因：
    echo   1. 浏览器未登录抖音/目标网站。
    echo   2. 浏览器配置路径不同，尝试 edge 或 firefox。
    echo   3. 网络需要代理，可添加 --proxy=http://127.0.0.1:7890。
    exit /b 1
)
