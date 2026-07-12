"""
Subtitle parsing module.
Supports WebVTT (.vtt) and SubRip (.srt) formats.
Strips HTML tags, timing cues, and cue identifiers to produce clean text.
"""

import re
from typing import Optional


_VTT_TIME = re.compile(
    r'(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s*-->\s*'
    r'(\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})'
)
_SRT_TIME = re.compile(
    r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*'
    r'(\d{2}:\d{2}:\d{2},\d{3})'
)
_TAG_STRIP = re.compile(r'<[^>]+>')


def _clean_line(line: str) -> str:
    """Remove HTML tags and excessive whitespace from a subtitle line."""
    return _TAG_STRIP.sub('', line).strip()


def _finalize(segments, text_parts, start, end):
    """Append a completed segment if we have text and timing."""
    if text_parts and start:
        text = ' '.join(text_parts)
        if text:
            segments.append({'start': start, 'end': end, 'text': text})


def parse_vtt(content: str) -> dict:
    """Parse WebVTT format subtitle content."""
    lines = content.strip().split('\n')
    segments = []
    text_parts = []
    cur_start = None
    cur_end = None

    for line in lines:
        line = line.strip()

        if line.startswith('WEBVTT') or line.startswith('NOTE'):
            continue

        if not line:
            _finalize(segments, text_parts, cur_start, cur_end)
            text_parts = []
            cur_start = None
            cur_end = None
            continue

        m = _VTT_TIME.search(line)
        if m:
            _finalize(segments, text_parts, cur_start, cur_end)
            text_parts = []
            cur_start = m.group(1)
            cur_end = m.group(2)
            continue

        if cur_start is None:
            continue

        cleaned = _clean_line(line)
        if cleaned:
            text_parts.append(cleaned)

    _finalize(segments, text_parts, cur_start, cur_end)

    return {
        'format': 'vtt',
        'segment_count': len(segments),
        'segments': segments,
        'full_text': ' '.join(s['text'] for s in segments),
    }


def parse_srt(content: str) -> dict:
    """Parse SubRip (.srt) format subtitle content."""
    lines = content.strip().split('\n')
    segments = []
    text_parts = []
    cur_start = None
    cur_end = None

    for line in lines:
        line = line.strip()

        if not line:
            _finalize(segments, text_parts, cur_start, cur_end)
            text_parts = []
            cur_start = None
            cur_end = None
            continue

        m = _SRT_TIME.search(line)
        if m:
            _finalize(segments, text_parts, cur_start, cur_end)
            text_parts = []
            cur_start = m.group(1)
            cur_end = m.group(2)
            continue

        # Skip numeric cue identifiers
        if line.isdigit() and cur_start is None:
            continue

        if cur_start is None:
            continue

        cleaned = _clean_line(line)
        if cleaned:
            text_parts.append(cleaned)

    _finalize(segments, text_parts, cur_start, cur_end)

    return {
        'format': 'srt',
        'segment_count': len(segments),
        'segments': segments,
        'full_text': ' '.join(s['text'] for s in segments),
    }


def _read_file(file_path: str) -> Optional[str]:
    """Read a subtitle file trying multiple encodings."""
    for encoding in ('utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'latin-1'):
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return f.read()
        except (UnicodeDecodeError, IOError):
            continue
    return None


def parse_subtitle(file_path: str) -> Optional[str]:
    """
    Parse a subtitle file and return plain text.

    Supports .vtt and .srt formats.
    Returns None if the file cannot be read or parsed.
    """
    content = _read_file(file_path)
    if content is None:
        return None

    if file_path.lower().endswith('.vtt') or content.strip().startswith('WEBVTT'):
        return parse_vtt(content)['full_text']

    return parse_srt(content)['full_text']


def parse_subtitle_detailed(file_path: str) -> Optional[dict]:
    """
    Parse a subtitle file and return a detailed dict with segments.

    Returns None if the file cannot be read or parsed.
    """
    content = _read_file(file_path)
    if content is None:
        return None

    if file_path.lower().endswith('.vtt') or content.strip().startswith('WEBVTT'):
        return parse_vtt(content)

    return parse_srt(content)
