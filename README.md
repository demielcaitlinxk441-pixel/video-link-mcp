# Video Link Analyzer

一个本地优先的视频链接分析与下载工具，包含 MCP 服务和 Windows 桌面下载器。下载记录、Cookie、AI 配置等默认保存在本机，不应提交到仓库。

## 快速开始

```bash
git clone https://github.com/demielcaitlinxk441-pixel/video-link-mcp.git
cd video-link-mcp
```

Windows 运行 `setup.bat`；macOS/Linux 运行 `chmod +x setup.sh && ./setup.sh`。安装脚本会创建虚拟环境、安装 Python 依赖、准备 Playwright Chromium，并执行基础自检。需要语音转文字时再加 `--with-stt`。

遇到问题请查看[安装与排错指南](docs/installation-and-troubleshooting.md)。

## Windows 桌面下载器

安装完成后运行 `scripts/start_desktop_app.bat`，或使用安装脚本创建的桌面快捷方式。粘贴视频链接、选择保存位置即可下载。抖音优先尝试移动分享页的完整 MP4，支持网络重试与断点续传；下载后会抽样检查视频和音频轨道并输出兼容的 MP4。队列中的等待任务和正在下载任务都可以取消。

## MCP 服务

核心入口是 `server.py`，提供链接识别、视频信息、下载、字幕转写和一站式分析工具。`mcp_config_example.json` 与 `mcp_http_config_example.json` 是配置模板。

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

微信视频号公共 Worker 默认关闭；如需启用，请明确设置 `WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER=true`，也可以改用自己的 Worker 或本地 Cookie。

> 公共 Worker 是第三方服务，启用后视频号分享链接会发送给该服务进行解析。对隐私有要求时请使用本地 Cookie 或自己部署的 Worker。

## 手机版安装包

仓库不再放置手机版源码、Android SDK、构建缓存或旧安装包，只通过 GitHub Releases 发布最新 Android APK。打开仓库的 **Releases**，进入最新版本，在 **Assets** 下载 `video-link-v37.apk`。

当前发布包：

- 版本：`0.4.0`（versionCode `37`）
- 文件：`video-link-v37.apk`
- SHA-256：`03A3A34AD402FCFD361E793C35794D44FE6C74E9FCB104F8B3EF460D6A978CE6`

手机端安装不需要 Node.js、Java/JDK 或 Android SDK；只需允许安装来自浏览器或文件管理器的应用。若 Android 提示无法安装，请先卸载旧版，再重新下载完整 APK。

## 抖音与 Cookie

桌面版抖音下载优先使用移动分享页直链，通常不需要浏览器 Cookie。受保护的平台可在 MCP 调用中传入 `cookies_from_browser` 或 Netscape 格式的 `cookies.txt`。不要把真实 Cookie、API Key、下载视频或本地配置提交到仓库。

## 目录结构

详见[项目结构说明](docs/project-structure.md)。

```text
video-link-mcp/
├── server.py                 MCP 服务入口
├── desktop_app.py            Windows 桌面下载器
├── lib/                      下载、识别、字幕、转写和视频号模块
├── scripts/                  安装、启动和诊断脚本
├── tests/                    离线测试
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

不要提交真实 Cookie、API Key、`.env`、视频文件、虚拟环境、Node 依赖或 Android/iOS 构建产物。项目采用 MIT 许可证，详见 [LICENSE](LICENSE)。

Windows 桌面版使用当前账户的 DPAPI 加密保存视频号授权和 AI API Key，明文密钥不会写入 `settings.json`。

## 许可证

MIT License
