# Changelog

## Unreleased

- Made FFmpeg diagnostics use the same executable search as the downloader.
- Disabled the public WeChat Channels Worker by default; enabling it now requires explicit opt-in.
- Improved automated repository verification and cleaned unused assets.
- Cached FFmpeg discovery and removed repeated yt-dlp page extraction.
- Replaced full-file compatibility decoding with fast start/end sampling and faster conversion settings.
- Added resumable direct downloads, automatic network retries, and active queue cancellation.
- Replaced fixed browser waits with early completion when media is detected.
- Encrypted desktop AI API keys with Windows DPAPI and migrated older plaintext settings.
- Fixed Douyin browser fallback stopping after the video-only stream before delayed audio arrived.
- Recognized legacy `chenzhongtech.com` Kuaishou share links and routed them to the Kuaishou browser downloader.

## 0.4.0 - 2026-08-08

- Added the Windows desktop downloader, selectable download folder, and automatic desktop shortcut creation.
- Improved Douyin downloads with mobile-page and Playwright fallbacks, audio-track checks, and compatible MP4 output.
- Added installation diagnostics and fresh-machine setup scripts for Windows, macOS, and Linux.
- Removed the superseded browser panel so the project has one clear desktop entry point.
- Changed the project license to MIT.
- Removed the Android source tree and old build artifacts from the repository.
- Published the latest Android package as `video-link-v37.apk` in GitHub Releases only.
