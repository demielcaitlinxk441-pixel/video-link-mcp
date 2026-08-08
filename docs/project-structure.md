# 项目结构

## 桌面与 MCP

- `server.py`：MCP 服务入口。
- `desktop_app.py`：Windows 桌面下载器入口。
- `lib/`：链接识别、下载、字幕、转写和视频号 API。
- `scripts/`：安装、启动、诊断和命令行辅助脚本。
- `tests/`：离线单元测试。

## 手机

- `mobile-app/`：独立 Expo / React Native 工程，下载和知识库保存在手机本地。

手机工程不依赖桌面 MCP 服务；桌面端和手机端是两个独立运行目标。

## 文档与配置

- `docs/`：安装、排错和项目说明。
- `assets/`：桌面图标等发布资源。
- `requirements.txt`：桌面/MCP 核心 Python 依赖。
- `requirements-stt.txt`：可选语音转文字依赖。
- `.env.example`：环境变量示例，不包含真实密钥。

## 不应进入仓库的内容

虚拟环境、下载视频、Cookie、`.env`、AI 密钥、Playwright 缓存、Node 依赖、Android/iOS 构建产物和本机 SDK 配置均属于本机数据，已由 `.gitignore` 排除。
