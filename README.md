# Video Link Analyzer - MCP Server

一个独立的 MCP (Model Context Protocol) 服务器，提供**链接类型智能识别**和**视频下载分析**能力。

可被 WorkBuddy、Codex 或任何 MCP 兼容客户端连接使用。

---

## 从私有 GitHub 仓库安装

每台电脑都应从仓库重新创建虚拟环境；不要复制或提交 `venv/`、下载视频、浏览器 Cookie 或 `.env` 文件。

```bash
git clone <你的私有仓库地址>
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

需要无字幕语音转写时，在命令后加 `--with-stt`。安装脚本会创建本机 `venv/`、安装 Chromium、运行 `scripts/verify.py` 和 `diagnose.py`，并打印可复制的 MCP 配置。若诊断提示未安装 ffmpeg，请按系统安装后重新运行 `diagnose.py`。

更新时执行 `git pull`，然后再次运行对应的安装脚本和 `diagnose.py`。登录 Cookie 和视频号 Cookie 只能在当前电脑的浏览器或 MCP 环境变量中配置，不能提交到仓库。

---

## 功能概览

| 工具 | 功能 | 说明 |
|------|------|------|
| `detect_link_type` | 链接类型识别 | 判断 URL 是视频/文章/设计页面，支持 16+ 平台 |
| `get_video_info` | 视频元数据 | 获取标题、时长、描述等，不下载文件 |
| `download_video` | 视频下载 | 下载视频+音频+字幕（yt-dlp），yt-dlp 失败时自动切换 Playwright 拦截下载；微信视频号支持直接 API 调用（无第三方依赖）和 Worker API 兜底 |
| `extract_transcript` | 语音转文字 | 字幕不可用时用 Whisper 识别（可选） |
| `analyze_video` | 一站式分析 | 下载→字幕→STT兜底，返回完整分析数据，支持 Cookie/代理 |

---

## 支持的视频平台

YouTube、哔哩哔哩、Vimeo、抖音、TikTok、Twitter/X、Instagram、微博、腾讯视频、优酷、爱奇艺、知乎视频、小红书、斗鱼、虎牙、**微信视频号**（直接 API 调用或 Worker API 兜底），以及直接视频文件链接（.mp4/.mkv 等）。

---

## 快速开始

### 1. 运行安装脚本

```bat
cd video-link-mcp
setup.bat
```

脚本会自动：
- 创建 Python 虚拟环境（`venv/`）
- 安装核心依赖（`mcp`、`yt-dlp`）
- 检查 ffmpeg 是否可用
- 输出 MCP 配置 JSON

### 2. 安装 ffmpeg（视频合并需要）

```bat
winget install ffmpeg
```

或从 [ffmpeg.org](https://ffmpeg.org/download.html) 下载。

### 3. （可选）安装语音转文字

当视频没有字幕时，可用 Whisper 进行语音识别：

```bat
venv\Scripts\pip install faster-whisper
```

### 4. 配置 MCP 客户端

#### WorkBuddy

编辑 `~/.workbuddy/mcp.json`，添加：

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

#### Codex

将同样的 `video-link-analyzer` 配置添加到 Codex 的 MCP 配置文件中。

> 将路径替换为实际的项目路径。运行 `setup.bat` 后会自动打印完整配置。

### 5. 运行测试

```bat
venv\Scripts\python.exe scripts\verify.py
```

---

## 项目结构

```
video-link-mcp/
├── server.py                 # MCP 服务器入口（定义 5 个工具）
├── lib/
│   ├── __init__.py
│   ├── detector.py           # 链接类型检测（URL匹配 + 页面分析）
│   ├── downloader.py         # 视频下载（yt-dlp + ffmpeg + Playwright 兜底 + 视频号集成）
│   ├── wechat_channels_api.py # 微信视频号下载（直接 API 调用 + Worker API 兜底）
│   ├── playwright_downloader.py # Playwright 网络拦截下载（抖音/TikTok/小红书 兜底）
│   ├── subtitle_parser.py    # 字幕解析（VTT/SRT → 纯文本）
│   └── transcriber.py        # 语音转文字（faster-whisper / openai-whisper）
├── requirements.txt          # 核心依赖
├── requirements-stt.txt      # 可选依赖（语音转文字）
├── setup.bat                 # Windows 一键安装脚本
├── scripts/                  # 命令行辅助工具与离线自检
│   ├── verify.py             # 离线自检脚本
│   ├── intercept_download.py # Playwright 拦截下载独立脚本
│   ├── download_direct.py    # 命令行直接下载脚本
│   └── download_with_cookies.bat # 使用浏览器 Cookie 下载
├── mcp_config_example.json   # MCP 配置示例
├── .gitignore               # Git 忽略规则（排除 venv/缓存/调试文件）
└── README.md
```

---

## 工具详细说明

### detect_link_type

```
输入: url (string)
输出: {
  "type": "video" | "article" | "design_page" | "unknown",
  "platform": "YouTube" | "Bilibili" | ... | null,
  "details": "描述信息",
  "confidence": 0.0-1.0
}
```

识别逻辑（三层）：
1. URL 模式匹配 — 已知视频平台域名（置信度 0.95）
2. 直接视频文件 — .mp4/.mkv 等扩展名（置信度 0.90）
3. 页面元数据分析 — 抓取 HTML 检查 video 标签、og:type、文本密度等（置信度 0.55-0.85）

### analyze_video（推荐使用）

一站式调用，自动完成完整链路：

```
输入: url, output_dir (可选)
输出: {
  "success": true,
  "video_path": "/path/to/video.mp4",
  "subtitle_path": "/path/to/subtitle.vtt",
  "transcript": "字幕或语音转文字的文本内容",
  "transcript_source": "subtitle" | "whisper" | "none",
  "metadata": {
    "title": "...",
    "duration": 300,
    "description": "...",
    "uploader": "...",
    ...
  }
}
```

流程：
1. 下载视频（普通平台用 yt-dlp 最高画质合并 MP4；微信视频号走直接 API 或 Worker API 下载）
2. 尝试获取中文字幕（zh-Hans → zh → en）
3. 有字幕 → 直接返回字幕文本
4. 无字幕 → 尝试 Whisper 语音转文字
5. 返回完整数据供 AI 进一步分析

---

## 依赖说明

| 依赖 | 用途 | 是否必须 |
|------|------|----------|
| `mcp` | MCP 协议 SDK | 必须 |
| `yt-dlp` | 视频下载 | 必须 |
| ffmpeg | 视频合并 + 音频提取 | 必须 |
| `playwright` | Playwright 拦截下载兜底（抖音/TikTok/小红书） | 推荐 |
| `faster-whisper` | 语音转文字 | 可选（无字幕时需要） |
| `openai-whisper` | 语音转文字（备选） | 可选 |

### 环境变量

| 环境变量 | 用途 | 是否必须 |
|----------|------|----------|
| `WECHAT_CHANNELS_YUANBAO_COOKIE` | 微信视频号直接 API 模式（从 yuanbao.tencent.com 获取 Cookie） | 推荐（否则走 Worker 兜底） |
| `WECHAT_CHANNELS_WORKER_URL` | 自定义 Worker API URL（设置即表示同意将链接交给该 Worker） | 可选 |
| `WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER` | 是否允许将链接发送给默认公共 Worker | 默认 `true` |

---

## 抖音 / 需要 Cookie 的平台下载指南

抖音、TikTok 等平台在反爬升级后，经常会要求提供登录 Cookie 才能下载，错误信息通常是：

```
Fresh cookies needed
```

本项目提供了多种方式解决：

### 方式 1：自动读取浏览器 Cookie（推荐）

`download_video`、`get_video_info`、`analyze_video`、`extract_transcript` 四个工具都支持 `cookies_from_browser` 参数。

支持的浏览器：`chrome`、`edge`、`firefox`、`safari`、`opera`、`brave`。

**在 WorkBuddy / Codex 中调用示例：**

```json
{
  "url": "https://www.douyin.com/video/123456789",
  "cookies_from_browser": "chrome"
}
```

yt-dlp 会自动从你登录过抖音的 Chrome 中读取 Cookie。

### 方式 2：命令行一键下载脚本

```bat
cd video-link-mcp
scripts\download_with_cookies.bat https://www.douyin.com/video/123456789 chrome
```

如果要换浏览器：

```bat
scripts\download_with_cookies.bat https://www.douyin.com/video/123456789 edge
```

指定输出目录：

```bat
scripts\download_with_cookies.bat https://www.douyin.com/video/123456789 chrome C:\Downloads
```

### 方式 3：使用导出的 cookies.txt

1. 安装浏览器扩展：[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckofkjlflfglhaegmbghhn)
2. 在抖音网页版登录后，点击扩展导出 `cookies.txt`
3. 调用时传入 `cookies_file` 参数：

```json
{
  "url": "https://www.douyin.com/video/123456789",
  "cookies_file": "C:\\Users\\you\\Downloads\\cookies.txt"
}
```

### 方式 4：直接命令行使用 yt-dlp

```bat
venv\Scripts\yt-dlp.exe --cookies-from-browser chrome "https://www.douyin.com/video/123456789"
```

或使用代理：

```bat
venv\Scripts\yt-dlp.exe --cookies-from-browser chrome --proxy http://127.0.0.1:7890 "https://www.douyin.com/video/123456789"
```

### 关于 `modal_id` 链接

你收到的抖音精选链接可能是这种格式：

```
https://www.douyin.com/jingxuan?modal_id=123456789
```

yt-dlp 不支持这种格式。本项目会自动将其转换为：

```
https://www.douyin.com/video/123456789
```

所以你可以直接把 `jingxuan?modal_id=...` 的链接丢进来。

---

## 常见问题

**Q: 下载的视频没有字幕怎么办？**

A: 安装 `faster-whisper` 后，`analyze_video` 工具会自动用 Whisper 进行语音转文字。或单独调用 `extract_transcript` 工具。

**Q: 支持哪些视频平台？**

A: 任何 yt-dlp 支持的平台。完整列表见 [yt-dlp 支持站点](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)。

**Q: 下载的文件保存在哪里？**

A: 默认保存在系统临时目录的 `video-link-analyzer/` 子目录下。可通过 `output_dir` 参数指定其他路径。

**Q: 抖音下载报错 "Fresh cookies needed" 怎么办？**

A: 有三层兜底机制：

1. **先传 Cookie 参数**：调用时传入 `"cookies_from_browser": "chrome"`（或 edge / firefox），详见上方「抖音 / 需要 Cookie 的平台下载指南」。
2. **自动 Playwright 兜底**：如果 yt-dlp 仍然失败（如 Chrome DPAPI 加密问题、Edge 数据库锁定），`download_video` 和 `analyze_video` 会**自动切换到 Playwright 拦截模式**——用无头浏览器打开视频页面，拦截真实视频 URL 直接下载，不需要 Cookie。
3. **手动用脚本**：运行 `venv\Scripts\python.exe scripts\intercept_download.py "抖音链接"` 直接走 Playwright 拦截。

Playwright 兜底是全自动的，你不需要额外操作。首次使用前确保已安装：

```bat
venv\Scripts\pip.exe install playwright
venv\Scripts\python.exe -m playwright install chromium
```

**Q: MCP 工具新增了哪些参数？**

A: 以下四个工具都新增了可选参数：

- `cookies_from_browser`: 自动读取浏览器 Cookie，例如 `"chrome"`、`"edge"`、`"firefox"`
- `cookies_file`: 传入 Netscape 格式的 `cookies.txt` 文件路径
- `proxy`: 代理地址，例如 `"http://127.0.0.1:7890"`

**Q: 如何在 WorkBuddy 中启用？**

A: 配置 `~/.workbuddy/mcp.json` 后，在 WorkBuddy 的连接器管理页面点击「Trust」信任该 MCP 服务器即可。

---

## 微信视频号下载指南

微信视频号的视频流地址仅通过 `WeixinJSBridge` 在微信 App 内部传递，Web API 不暴露视频 URL，因此 yt-dlp 和 Playwright 均无法直接下载。

本项目采用 **双模式下载策略**，优先使用直接 API 调用（无第三方依赖），未配置时自动回退到 Worker API：

### 模式 1：直接 API 调用（推荐，无第三方依赖）

在本地直接调用腾讯元宝 API + 微信视频号 API 完成链接解析和视频下载，不依赖任何第三方服务。

**工作原理：**
1. 调用 `https://yuanbao.tencent.com/api/weixin/get_parse_result` 解析分享链接 → 获取 `export_id` 和 `playable_url`
2. 从 `playable_url` 提取 `token` 和 `eid`
3. 调用 `https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info` → 获取视频直链 + 元数据
4. 直接从 CDN（`finder.video.qq.com`）下载有效 MP4 文件（无需解密）

**配置方式：**

获取元宝 Cookie：
1. 用浏览器打开 [https://yuanbao.tencent.com](https://yuanbao.tencent.com) 并登录
2. 打开浏览器开发者工具（F12）→ Network 标签
3. 随便发一条消息，找到任意 `api/chat` 请求
4. 复制请求头中完整的 `Cookie` 值

然后通过以下任一方式配置：

**方式 A — 环境变量（推荐）：**

在 MCP 配置中设置环境变量：
```json
{
  "mcpServers": {
    "video-link-analyzer": {
      "command": "python",
      "args": ["server.py"],
      "env": {
        "WECHAT_CHANNELS_YUANBAO_COOKIE": "你的元宝Cookie"
      }
    }
  }
}
```

**方式 B — 工具参数：**

调用 `download_video`、`get_video_info` 或 `analyze_video` 时传入 `yuanbao_cookie` 参数：
```json
{
  "url": "https://weixin.qq.com/sph/AFWYoXF5Bw",
  "yuanbao_cookie": "你的元宝Cookie"
}
```

配置后，返回结果中 `download_method` 字段为 `"wechat_channels_direct"`。

### 模式 2：Worker API（默认启用）

如果未配置元宝 Cookie，系统会默认调用公共 Cloudflare Worker API（`sph.litao.workers.dev`）解析视频号链接。若不希望将链接发送给公共服务，请在 MCP 配置中设置 `WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER=false`。

**关闭方式：** 在 MCP 配置中设置：

```json
{
  "env": {
    "WECHAT_CHANNELS_ALLOW_PUBLIC_WORKER": "false"
  }
}
```

返回结果中 `download_method` 字段为 `"wechat_channels_worker"`。如不希望使用公共 Worker，可关闭该选项、配置元宝 Cookie 或自建 Worker。

**自定义 Worker URL：** 如果公共 Worker 不可用，可以自部署 Worker（参考 [ltaoo/wx_channels_download](https://github.com/ltaoo/wx_channels_download) 的 `sph_deploy` 命令），然后设置环境变量：
```json
{
  "env": {
    "WECHAT_CHANNELS_WORKER_URL": "https://your-worker.your-subdomain.workers.dev/api/fetch_video_profile"
  }
}
```

### 支持的链接格式

- `https://weixin.qq.com/sph/<id>`（分享链接）
- `https://channels.weixin.qq.com/finder-preview`
- `https://channels.weixin.qq.com/web/pages/feed/`
