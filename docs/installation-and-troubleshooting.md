# 安装与排错指南

本文覆盖桌面 MCP 服务、Windows 下载器和 `mobile-app/` 手机工程。先完成对应环境，再运行自检。

## Windows 桌面版

安装前准备：

- Python 3.10–3.13
- Git
- FFmpeg

运行：

```bat
setup.bat
```

脚本会创建 `venv/`、安装核心依赖、安装 Chromium、检查 FFmpeg、运行 `scripts/verify.py` 和 `diagnose.py`。路径过深时会把运行时放到 `%LOCALAPPDATA%\VideoLinkAnalyzer\runtime`。

手动检查：

```bat
venv\Scripts\python.exe scripts\verify.py
venv\Scripts\python.exe diagnose.py
venv\Scripts\python.exe -m unittest discover -s tests
```

核心依赖和 Chromium 必须通过。FFmpeg 需要能被下载器找到；如果 FFmpeg 已通过 winget 安装但诊断显示未找到，请把 FFmpeg 的 `bin` 目录加入系统 PATH，重新打开终端后再检查。

## MCP 配置

使用 `mcp_config_example.json` 生成客户端配置。配置中的 Python 和 `server.py` 必须指向当前电脑的绝对路径，不能复制其他电脑的 `venv/`。

HTTP 模式运行：

```bat
scripts\start_http_mcp.bat
```

默认地址为 `http://127.0.0.1:8000/mcp`；端口冲突时传入其他端口。

## 抖音下载

当前桌面版优先读取移动分享页里的完整 MP4 地址，通常比浏览器拦截更快，也不依赖 Cookie。若页面改版导致直连失败，程序会继续尝试 yt-dlp 或备用解析。

若平台要求 Cookie，可在 MCP 调用中传入：

```json
{
  "cookies_from_browser": "firefox"
}
```

也可以传入 Netscape 格式的 `cookies.txt`。新版 Chrome/Edge 可能因 DPAPI 应用绑定加密而无法被 yt-dlp 解密，这不是项目 Cookie 参数写错。

## 手机原生工程

`mobile-app/` 是独立的 Expo / React Native 工程，不是桌面服务的启动脚本。

```bash
cd mobile-app
npm install
npx expo start
```

环境要求：

- Node.js 22.13+
- Expo CLI / EAS CLI
- 本地 Android 构建：JDK 17+、`JAVA_HOME`、Android SDK 和 Gradle
- iPhone 真机：Apple Developer 签名

如果只使用 EAS 云构建，不需要本机 Gradle，但仍需要 Node.js。Android SDK 路径应写在本机 `android/local.properties` 中；该文件不提交到仓库。

TypeScript 检查报错时，先确认 Node.js 已加入 PATH，并在 `mobile-app/` 目录运行 `npm install`。如果错误来自项目自带 `android-sdk/` 中的第三方 JavaScript 文件，应将该 SDK 目录排除在 tsconfig 检查范围之外，不要把它误判为 `App.tsx` 业务代码错误。

## 常见问题

### Python 找不到

重新运行 `setup.bat`。脚本支持 Python 3.10–3.13；如果系统没有合适版本，会尝试通过 winget 安装 Python 3.13。

### Playwright Chromium 缺失

```bat
venv\Scripts\python.exe -m playwright install chromium
```

### FFmpeg 缺失

```bat
winget install --id Gyan.FFmpeg.Shared --exact
```

安装后重新打开终端，并确认 `ffmpeg -version` 能运行。

### 语音转文字不可用

语音转文字是可选功能：

```bat
setup.bat --with-stt
```

### 下载失败或没有音频

先确认使用的是最新代码，删除失败任务后重新提交链接。抖音下载应优先走移动分享页直连；若仍失败，检查页面是否需要登录 Cookie，并确认 FFmpeg 可用。

## 隐私提醒

不要把 Cookie、API Key、下载视频、日志或本机配置上传到 GitHub。公共 Worker、代理和第三方 AI 服务可能接收你主动发送的链接或文本，请按需关闭或替换。
