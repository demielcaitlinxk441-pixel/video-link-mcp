# 安装与排错指南

本文覆盖桌面 MCP 服务和 Windows 下载器。手机版只提供 GitHub Releases 中的最新 APK，不需要在本机搭建 Android 构建环境。

## Windows 桌面版

准备 Python 3.10–3.13、Git 和 FFmpeg，然后运行：

```bat
setup.bat
```

脚本会创建 `venv/`、安装依赖、准备 Chromium，并运行 `scripts/verify.py` 与 `diagnose.py`。路径过深时，运行时文件会放在 `%LOCALAPPDATA%\VideoLinkAnalyzer\runtime`。

手动检查：

```bat
venv\Scripts\python.exe scripts\verify.py
venv\Scripts\python.exe diagnose.py
venv\Scripts\python.exe -m unittest discover -s tests
```

FFmpeg 即使已经安装，若未加入系统 PATH，诊断脚本仍可能提示找不到；下载器会在常见安装目录中继续查找。若要让命令行也能直接使用，请把 FFmpeg 的 `bin` 目录加入 PATH，并重新打开终端。

## 抖音下载没有声音

桌面版会优先读取移动分享页的完整 MP4，并在保存后检查音频轨道。若仍无声：

1. 删除失败任务后重新粘贴完整分享链接。
2. 确认下载器能找到 FFmpeg。
3. 若页面要求登录，在 MCP 调用中传入 `cookies_from_browser` 或 Netscape 格式的 `cookies.txt`。

## 手机版 APK

从仓库的 **Releases → 最新版本 → Assets** 下载 `video-link-v37.apk`。手机版安装不需要 Node.js、Java/JDK、Gradle 或 Android SDK，这些构建工具不再随仓库发布。

当前包信息：`0.4.0` / versionCode `37`，SHA-256 为 `03A3A34AD402FCFD361E793C35794D44FE6C74E9FCB104F8B3EF460D6A978CE6`。

如果安装失败：

- 重新下载，确认文件大小约 70 MB，避免下载未完成的文件；
- 卸载旧版后再安装；
- 在系统设置中允许当前浏览器或文件管理器安装未知来源应用；
- 只使用 Releases 中的最新 APK，不要使用旧版本或构建目录中的临时文件。

## 语音转文字

这是可选功能：

```bat
setup.bat --with-stt
```

不安装语音依赖不会影响普通视频下载。

## 隐私提醒

不要把 Cookie、API Key、下载视频、日志或本地配置上传到 GitHub。公开 Worker、代理和第三方 AI 服务可能接收到你主动发送的链接或文本，请按需关闭或替换。

