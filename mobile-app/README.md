# 视频下载助手 · 手机独立版

这是 Android + iPhone 的独立移动端工程（Expo / React Native）。它不需要电脑后台：

- 视频直链直接下载到手机应用的本地 `downloads` 目录；
- 下载记录和知识库索引使用手机本地 SQLite；
- 只有点击“加入知识库”才会生成分类/摘要，不会自动上传视频文件；
- AI 使用用户在“设置”中填写的 OpenAI 兼容接口，API Key 写入手机安全存储；
- AI 问答只把本地知识库的文字索引发送给模型，不发送视频文件。

Android 还提供“用 Termux / yt-dlp 下载”入口。它需要用户另外安装官方 Termux，并在 Termux 中安装 yt-dlp、FFmpeg，同时开启 `allow-external-apps` 和“Run commands in Termux environment”权限；这是 Android 的安全要求，App 不会静默安装或执行外部程序。iPhone 不提供此入口。

## 本地运行

需要 Node.js 22.13+（Expo SDK 57 的最低版本）。首次安装依赖后：

```text
npm install
npx expo start
```

### 不使用云端额度：本机生成 Android APK

在 Windows 上安装 Android Studio，并在 SDK Manager 中安装 Android SDK。然后在 PowerShell 中运行：

```powershell
.\build-local-apk.ps1
```

脚本会自动使用 Android Studio 自带的 Java、配置 SDK，并将可直接安装的 APK 输出到 `dist/video-link-v4-local.apk`。整个过程不使用 EAS，也没有云端构建额度限制。

如果只使用 Expo 云端构建，仍可运行：

```text
npx eas login
npx eas build --platform android --profile preview
```

同时生成 Android/iOS 构建：

```text
npx eas build --platform all
```

iPhone 真机安装需要 Apple Developer 签名；Android 预览配置会输出 APK。平台受限链接（例如某些短视频 App 的受保护页面）暂不保证能在手机端直接解析，第一版先稳定支持可下载直链。
