# 项目结构

## 桌面端与 MCP

- `server.py`：MCP 服务入口。
- `desktop_app.py`：Windows 桌面下载器入口。
- `lib/`：链接识别、下载、字幕、转写和视频号 API。
- `scripts/`：安装、启动、诊断和命令行辅助脚本。
- `tests/`：离线单元测试。

## 文档与配置

- `docs/`：安装、排错和项目说明。
- `assets/`：桌面图标和发布资源。
- `requirements.txt`：桌面端核心 Python 依赖。
- `requirements-stt.txt`：可选语音转文字依赖。
- `.env.example`：不含真实密钥的环境变量示例。

## 手机版发布策略

手机版源码、Android SDK、Node 依赖、Gradle 缓存和构建产物不放在这个仓库中。仓库只在 GitHub Releases 提供最新 Android 安装包：当前为 `video-link-v37.apk`（0.4.0，versionCode 37）。这样下载者无需理解或安装手机端构建环境，也不会误用旧 APK。

## 不应进入仓库的内容

虚拟环境、下载视频、Cookie、`.env`、AI 密钥、Playwright 缓存、Node 依赖、Android/iOS 构建产物和本地 SDK 都属于本机数据，已由 `.gitignore` 排除。
