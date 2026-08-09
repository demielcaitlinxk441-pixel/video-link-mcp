"""Local, current-user storage for optional platform credentials."""

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path


APP_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'VideoLinkAnalyzer'
CREDENTIALS_FILE = APP_DIR / 'credentials.json'
_YUANBAO_COOKIE = 'yuanbao_cookie'
_AI_API_KEY = 'ai_api_key'


class _DataBlob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]


def _blob(value: bytes):
    buffer = ctypes.create_string_buffer(value)
    return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _protect(value: str) -> str:
    if os.name != 'nt':
        raise RuntimeError('Local credential storage is currently supported on Windows only.')
    source, source_buffer = _blob(value.encode('utf-8'))
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), 'Video Link Analyzer', None, None, None, 0, ctypes.byref(result)
    ):
        raise ctypes.WinError()
    try:
        return base64.b64encode(ctypes.string_at(result.pbData, result.cbData)).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def _unprotect(value: str) -> str:
    if os.name != 'nt':
        return ''
    encrypted, encrypted_buffer = _blob(base64.b64decode(value))
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(encrypted), None, None, None, None, 0, ctypes.byref(result)
    ):
        return ''
    try:
        return ctypes.string_at(result.pbData, result.cbData).decode('utf-8')
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def _credential_data() -> dict:
    try:
        content = json.loads(CREDENTIALS_FILE.read_text(encoding='utf-8'))
        return content if isinstance(content, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _get_credential(name: str) -> str:
    try:
        return _unprotect(_credential_data().get(name, ''))
    except (OSError, ValueError):
        return ''


def _save_credential(name: str, value: str) -> None:
    normalized = value.strip()
    if not normalized:
        raise ValueError('授权信息不能为空。')
    content = _credential_data()
    content[name] = _protect(normalized)
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(json.dumps(content), encoding='utf-8')


def _clear_credential(name: str) -> None:
    content = _credential_data()
    if name not in content:
        return
    content.pop(name, None)
    if content:
        CREDENTIALS_FILE.write_text(json.dumps(content), encoding='utf-8')
    else:
        try:
            CREDENTIALS_FILE.unlink()
        except FileNotFoundError:
            pass


def get_yuanbao_cookie() -> str:
    """Return the credential decryptable by this Windows user, if present."""
    return _get_credential(_YUANBAO_COOKIE)


def save_yuanbao_cookie(cookie: str) -> None:
    """Encrypt the cookie with Windows DPAPI before writing it locally."""
    _save_credential(_YUANBAO_COOKIE, cookie)


def clear_yuanbao_cookie() -> None:
    """Remove the local credential for this Windows user."""
    _clear_credential(_YUANBAO_COOKIE)


def get_ai_api_key() -> str:
    """Return the locally encrypted AI API key."""
    return _get_credential(_AI_API_KEY)


def save_ai_api_key(api_key: str) -> None:
    """Encrypt the AI API key with Windows DPAPI."""
    _save_credential(_AI_API_KEY, api_key)


def clear_ai_api_key() -> None:
    """Remove only the AI API key while preserving platform credentials."""
    _clear_credential(_AI_API_KEY)
