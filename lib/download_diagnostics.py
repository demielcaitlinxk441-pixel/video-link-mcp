"""Structured, redacted download failures shared by desktop and MCP clients."""

from __future__ import annotations

import os
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


STAGES = {
    'link': '链接解析',
    'auth': '授权',
    'video': '视频下载',
    'audio': '音频下载',
    'subtitle': '字幕下载',
    'merge': '音视频合并',
    'convert': '兼容转换',
    'save': '文件保存',
}

_SECRET_KEYS = {
    'cookie', 'authorization', 'token', 'access_token', 'refresh_token',
    'signature', 'sign', 'x-bogus', 'ms_token', 'mstoken', 'sessionid',
    'sig', 'lsig', 'x-signature', 'expires', 'expire', 'auth_key',
    'wssecret', 'wstime',
}


def _redact_url(match: re.Match) -> str:
    value = match.group(0)
    try:
        parts = urlsplit(value)
        query = []
        for key, item in parse_qsl(parts.query, keep_blank_values=True):
            query.append((key, '[REDACTED]' if key.lower() in _SECRET_KEYS else item))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))
    except ValueError:
        return '[URL]'


def redact(value: object) -> str:
    """Remove credentials, signed URL secrets and user-profile details."""
    text = str(value or '')
    text = re.sub(
        r'(?i)\b(cookie|authorization|access[_-]?token|refresh[_-]?token|sessionid)\b\s*[:=]\s*[^\s,;|]+',
        lambda match: f'{match.group(1)}=[REDACTED]', text,
    )
    text = re.sub(r'https?://[^\s|"\']+', _redact_url, text)
    profile = os.path.expanduser('~')
    if profile:
        text = re.sub(re.escape(profile), '%USERPROFILE%', text, flags=re.IGNORECASE)
    return text[:4000]


def _http_status(error: str) -> int | None:
    match = re.search(r'(?i)(?:HTTP(?: Error)?|status(?: code)?)\s*[:=]?\s*(\d{3})', error)
    return int(match.group(1)) if match else None


def classify_failure(error: object, *, default_stage: str = '链接解析') -> dict:
    """Map raw downloader errors to stable, user-actionable failure fields."""
    raw = str(error or '未知下载错误')
    lower = raw.lower()
    status = _http_status(raw)
    stage = default_stage
    code = 'DOWNLOAD_FAILED'
    reason = '下载没有完成。'
    action = '请复制诊断报告后重试；持续失败时根据失败阶段检查配置。'

    if 'wechat_channels_auth_failed' in lower:
        stage, code, reason = STAGES['auth'], 'WECHAT_CHANNELS_AUTH_FAILED', '视频号授权已失效或被平台拒绝。'
        action = '点击“视频号授权”，完成本人元宝账号登录后重试。'
    elif 'wechat_channels_auth_parse_failed' in lower:
        stage, code, reason = STAGES['auth'], 'WECHAT_CHANNELS_AUTH_PARSE_FAILED', '视频号授权未能解析这条分享链接。'
        action = '点击“视频号授权”重新登录后重试；若仍失败，请确认链接能在官方视频号中正常打开。'
    elif 'wechat_channels_parse_failed' in lower:
        stage, code, reason = STAGES['link'], 'WECHAT_CHANNELS_PARSE_FAILED', '视频号平台未返回这条链接的可下载信息。'
        action = '确认分享链接完整且能在官方视频号打开，稍后重试。'
    elif 'subtitle' in lower or '字幕' in raw:
        stage, code, reason = STAGES['subtitle'], 'SUBTITLE_FAILED', '字幕获取失败。'
        action = '视频仍可使用；稍后单独重试字幕。'
    elif 'audio' in lower or '音轨' in raw or '音频' in raw:
        stage, code, reason = STAGES['audio'], 'AUDIO_FAILED', '音频获取失败。'
        action = '保留已下载画面，更新平台授权后重试音频。'
    elif 'ffmpeg' in lower or 'ffprobe' in lower or '转换' in raw:
        stage, code, reason = STAGES['convert'], 'FFMPEG_UNAVAILABLE', '缺少或无法运行媒体处理组件。'
        action = '运行安装程序修复 FFmpeg，然后重试兼容转换。'
    elif any(token in lower for token in ('no space', 'disk full', 'permission denied', 'access is denied')) or '无法保存' in raw:
        stage, code, reason = STAGES['save'], 'FILE_WRITE_FAILED', '文件无法写入保存位置。'
        action = '检查磁盘空间、目录权限和文件是否被占用。'
    elif status == 429:
        code, reason = 'RATE_LIMITED', '平台请求过于频繁。'
        action = '等待一段时间后重试，避免同时提交过多链接。'
    elif status in {401, 403, 412} or any(token in lower for token in ('fresh cookies', 'sign in', 'login required', 'authentication')):
        stage, code, reason = STAGES['auth'], 'AUTH_REQUIRED', '平台授权已失效或未被下载器读取。'
        action = '在软件中重新完成对应平台授权后重试。'
    elif status in {500, 502, 503, 504}:
        stage, code, reason = STAGES['video'], 'SERVICE_UNAVAILABLE', '平台媒体服务暂时不可用。'
        action = '保留临时文件，稍后使用断点续传重试。'
    elif any(token in lower for token in ('merge', 'mux', '合并')):
        stage, code, reason = STAGES['merge'], 'MERGE_FAILED', '音视频合并失败。'
        action = '检查 FFmpeg 后重新合并，无需重复下载已有媒体。'
    elif any(token in lower for token in ('download', 'timed out', 'connection', 'network')):
        stage, code, reason = STAGES['video'], 'VIDEO_DOWNLOAD_FAILED', '视频数据下载失败。'
        action = '检查网络后重试；已有临时文件将用于断点续传。'

    return {
        'error_code': code,
        'failed_stage': stage,
        'http_status': status,
        'reason': reason,
        'suggested_action': action,
        'raw_error': redact(raw),
    }


def normalize_result(result: dict, *, url: str = '') -> dict:
    """Add stable diagnostics while preserving all legacy result fields."""
    normalized = dict(result or {})
    method = normalized.get('download_method') or 'unknown'
    normalized.setdefault('download_method', method)
    normalized.setdefault('attempts', 1)
    artifacts = dict(normalized.get('artifacts') or {})
    for key in ('video_path', 'subtitle_path', 'source_video_path'):
        if normalized.get(key):
            artifacts.setdefault(key, normalized[key])
    normalized['artifacts'] = artifacts

    failure = None
    compatibility = normalized.get('compatibility') or {}
    if not normalized.get('success'):
        failure = classify_failure(normalized.get('error'))
        if normalized.get('failed_stage'):
            failure['failed_stage'] = normalized['failed_stage']
        if normalized.get('http_status'):
            failure['http_status'] = normalized['http_status']
    elif compatibility.get('status') == 'missing_audio':
        failure = classify_failure(compatibility.get('message') or '未检测到音轨')
        failure['error_code'] = 'AUDIO_MISSING'

    if failure:
        normalized['failure'] = failure
        normalized['error_code'] = failure['error_code']
        normalized['failed_stage'] = failure['failed_stage']
        normalized['http_status'] = failure['http_status']
        normalized['suggested_action'] = failure['suggested_action']
    else:
        normalized['failure'] = None
        normalized.setdefault('error_code', None)
        normalized.setdefault('failed_stage', None)
        normalized.setdefault('http_status', None)
        normalized.setdefault('suggested_action', '')

    normalized['diagnostics'] = {
        'source': redact(url),
        'method': method,
        'attempts': normalized.get('attempts', 1),
        'failure': failure,
        'artifacts': {
            key: os.path.basename(str(value)) if key.endswith('path') else redact(value)
            for key, value in artifacts.items()
        },
    }
    return normalized


def diagnostic_report(result: dict) -> str:
    """Create a concise report suitable for clipboard sharing."""
    normalized = normalize_result(result)
    failure = normalized.get('failure') or {}
    lines = [
        '视频下载诊断报告',
        f"结果：{'成功' if normalized.get('success') else '失败'}",
        f"下载方式：{normalized.get('download_method', 'unknown')}",
        f"失败阶段：{failure.get('failed_stage') or '无'}",
        f"错误代码：{failure.get('error_code') or '无'}",
        f"HTTP 状态：{failure.get('http_status') or '无'}",
        f"尝试次数：{normalized.get('attempts', 1)}",
        f"已完成内容：{', '.join(normalized.get('diagnostics', {}).get('artifacts', {}).keys()) or '无'}",
        f"原因：{failure.get('reason') or '无'}",
        f"处理建议：{failure.get('suggested_action') or '无'}",
        f"原始错误：{failure.get('raw_error') or '无'}",
    ]
    return redact('\n'.join(lines))
