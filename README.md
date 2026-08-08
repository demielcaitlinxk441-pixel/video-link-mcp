# Video Link Analyzer

一个本地优先的视频链接分析与下载工具，包含 MCP 服务、Windows 桌面下载器和独立的 Expo 手机工程。

视频、下载记录、Cookie 和 AI 配置默认保存在本机，不应提交到仓库。

## 快速开始

```bash
git clone https://github.com/demielcaitlinxk441-pixel/video-link-mcp.git
cd video-link-mcp
```

Windows：运行 `setup.bat`。它会创建 `venv/`、安装 Python 依赖、安装 Playwright Chromium、检查 FFmpeg，并运行离线自检。

macOS / Linux：运行 `chmod +x setup.sh && ./setup.sh`。

需要语音转文字时，在安装命令后加 `--with-stt`。更新代码后重新运行安装脚本和 `diagnose.py`。

遇到问题请查看[安装与排错指南](docs/installation-and-troubleshooting.md)。

## Windows 桌面下载器

安装完成后运行 `scripts/start_desktop_app.bat`，或使用安装脚本创建的桌面快捷方式。粘贴链接、选择保存位置即可下载。

普通平台使用 yt-dlp；抖音优先使用移动分享页直连完整 MP4，失败时再进入备用解析。下载完成后会检查视频和音频轨，并验证高兼容 MP4。

## MCP 服务

核心入口是 `server.py`，包含链接识别、视频信息、下载、字幕/转写和一站式分析工具。`mcp_config_example.json` 和 `mcp_http_config_example.json` 提供配置模板。

标准 MCP 配置示例：

```json
{
  "mcpServers": {
    "video-link-analyzer": {
      "command": "C:\\path\\to\\video-link-mcp\\venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\video-link-mcp\\server.py"]
    }
  }
}
```

微信视频号的公共 Worker 可通过 `WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER=false` 关闭；也可以配置自己的 Worker 或本地 Cookie。

## 手机独立版

`mobile-app/` 是独立的 Expo / React Native 工程，不依赖电脑后台。视频、下载记录和 SQLite 知识库保存在手机本地，AI 通过手机配置的 OpenAI 兼容接口访问。

```bash
cd mobile-app
npm install
npx expo start
```

Expo SDK 57 要求 Node.js 22.13+。本地 Android 构建还需要 JDK 17+、Android SDK 和 Gradle；iPhone 真机安装需要 Apple Developer 签名。也可以使用 EAS 云构建。

## 抖音与 Cookie

桌面版抖音会优先尝试移动分享页直连，因此通常不需要浏览器 Cookie。其他受保护平台可在 MCP 调用中传入 `cookies_from_browser` 或 `cookies_file`。新版 Chromium 可能因 DPAPI 应用绑定加密而无法读取 Cookie，此时使用导出的 Netscape 格式 `cookies.txt`。

## 目录结构

详见[项目结构说明](docs/project-structure.md)。

```text
video-link-mcp/
├── server.py                 MCP 服务入口
├── desktop_app.py            Windows 桌面下载器
├── lib/                      下载、识别、字幕、转写和视频号模块
├── scripts/                  安装、启动和诊断脚本
├── tests/                    离线测试
├── mobile-app/               Expo / React Native 手机工程
├── docs/                     安装与项目文档
├── assets/                   图标和发布资源
├── requirements.txt          核心 Python 依赖
└── requirements-stt.txt      可选语音转文字依赖
```

## 自检

```bat
venv\Scripts\python.exe scripts\verify.py
venv\Scripts\python.exe diagnose.py
venv\Scripts\python.exe -m unittest discover -s tests
```

## 安全与隐私

不要提交真实 Cookie、API Key、`.env`、视频文件、虚拟环境、Node 依赖或 Android/iOS 构建产物。默认下载和知识库数据只保存在本机。

项目采用 MIT 许可证，详见 [LICENSE](LICENSE)。

## 许可证

MIT License
