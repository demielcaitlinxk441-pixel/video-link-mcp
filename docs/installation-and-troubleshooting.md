# 安装与排错指南

本指南面向从公开 GitHub 仓库安装 Video Link Analyzer 的使用者。README 适合快速开始；遇到安装、更新或运行问题时再查看本页。

## 安装前准备

- Git
- Python 3.10 至 3.13
- ffmpeg（视频合并和语音转文字需要）

不要复制其他电脑的 `venv/`、浏览器 Cookie、`.env` 或已下载视频。每台电脑都应重新安装，并只保存自己的本机凭据。

## 从 GitHub 安装

```bash
git clone https://github.com/demielcaitlinxk441-pixel/video-link-mcp.git
cd video-link-mcp
```

Windows：

```bat
setup.bat
```

macOS / Linux：

```bash
chmod +x setup.sh
./setup.sh
```

需要在无字幕视频上使用语音转文字时，运行安装脚本时附加 `--with-stt`。安装脚本会创建本机虚拟环境、安装 Chromium、执行自检并打印 stdio MCP 配置。

## Windows 桌面下载器

Windows 上完成 `setup.bat` 后，安装脚本会自动在桌面创建 **Video Link Analyzer** 快捷方式。双击它即可打开独立下载窗口：粘贴视频链接、选择保存文件夹，然后点击“开始下载”。

若桌面快捷方式没有出现，可在项目目录双击运行：

```bat
scripts\start_desktop_app.bat
```

桌面下载器不需要 MCP 客户端；它与 MCP 共用相同的下载能力。下载位置与下载记录仅保存在当前电脑。

支持 HTTP MCP 的客户端可在当前电脑启动本机服务：

```bat
scripts\start_http_mcp.bat
```

Windows 以外的系统可运行：

```bash
venv/bin/python server.py --transport http
```

随后在兼容的客户端中使用 `http://127.0.0.1:8000/mcp`。该地址仅供当前电脑访问。

## 更新项目

在项目目录中执行：

```bash
git pull
```

然后重新运行对应系统的安装脚本和 `diagnose.py`，让依赖与浏览器组件同步到新版本。

## 常见问题

### Python 版本不符合要求

安装 Python 3.10 至 3.13，并确认 Windows 的 `python` 或 macOS/Linux 的 `python3` 已加入系统 PATH，然后重新运行安装脚本。

### 找不到 ffmpeg

Windows 可运行：

```bat
winget install ffmpeg
```

macOS 可运行：

```bash
brew install ffmpeg
```

Ubuntu / Debian 可运行：

```bash
sudo apt install ffmpeg
```

安装后执行 `diagnose.py` 确认环境状态。

### Chromium 未安装或 Playwright 下载失败

Windows：

```bat
venv\Scripts\python.exe -m playwright install chromium
```

macOS / Linux：

```bash
venv/bin/python -m playwright install chromium
```

### 缺少语音转文字功能

重新运行安装脚本并附加 `--with-stt`，或在现有虚拟环境安装 `requirements-stt.txt`。

### MCP 客户端没有显示工具

确认 MCP 配置中的 Python 与 `server.py` 路径属于当前电脑，然后重启 MCP 客户端。使用 HTTP MCP 时，先启动本机 HTTP 服务，并确认客户端填写的端口与启动命令一致。

## 本机凭据与视频号隐私

浏览器 Cookie、`cookies.txt`、`.env`、元宝 Cookie、下载文件和 `venv` 都只能保留在本机，绝不能提交到 GitHub 或发送给他人。

视频号在未配置元宝 Cookie 时，会默认将分享链接发送至公共 Worker 解析服务。若不希望使用该服务，请在 MCP 客户端的环境变量中设置：

```text
WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER=false
```

也可以配置自己的 `WECHAT_CHANNELS_WORKER_URL`，或使用本机的 `WECHAT_CHANNELS_YUANBAO_COOKIE` 直接解析。
