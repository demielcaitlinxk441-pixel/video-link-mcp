"""
Speech-to-text module.
Uses Whisper AI (faster-whisper or openai-whisper) to transcribe audio
when subtitles are not available.
This module is optional - the server works without it.
"""

import os
import subprocess
from typing import Optional

from .downloader import find_ffmpeg


def extract_audio(video_path: str, output_path: str = None) -> Optional[str]:
    """Extract audio from a video file as 16kHz mono WAV using ffmpeg."""
    if output_path is None:
        output_path = os.path.splitext(video_path)[0] + '_audio.wav'

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None

    try:
        cmd = [
            ffmpeg,
            '-i', video_path,
            '-vn',
            '-acodec', 'pcm_s16le',
            '-ar', '16000',
            '-ac', '1',
            '-y',
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=600)
        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
        return None
    except Exception:
        return None


def transcribe_audio(video_path: str, language: str = 'zh') -> dict:
    """
    Transcribe audio from a video file using Whisper.

    Tries faster-whisper first (faster, lighter), then falls back to
    openai-whisper. Returns an error dict if neither is installed.

    Args:
        video_path: Path to the video file.
        language: Language code for transcription (default: zh).

    Returns:
        dict with transcript text, segments, and engine info.
    """
    if not os.path.exists(video_path):
        return {
            'success': False,
            'error': f'Video file not found: {video_path}',
        }

    audio_path = extract_audio(video_path)
    if not audio_path:
        return {
            'success': False,
            'error': (
                'Failed to extract audio. '
                'Make sure ffmpeg is installed and accessible.'
            ),
        }

    try:
        # Try faster-whisper first (recommended)
        result = _try_faster_whisper(audio_path, language)
        if result.get('success'):
            return result

        # Fall back to openai-whisper
        result = _try_openai_whisper(audio_path, language)
        if result.get('success'):
            return result

        return {
            'success': False,
            'error': (
                'No speech-to-text engine available. Install one:\n'
                '  pip install faster-whisper  (recommended)\n'
                '  pip install openai-whisper'
            ),
            'audio_path': audio_path,
        }
    finally:
        if audio_path and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass


def _try_faster_whisper(audio_path: str, language: str) -> dict:
    """Attempt transcription with faster-whisper."""
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel('base', device='cpu', compute_type='int8')
        segments, info = model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            vad_filter=True,
        )

        seg_list = []
        text_parts = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                seg_list.append({
                    'start': round(seg.start, 2),
                    'end': round(seg.end, 2),
                    'text': text,
                })
                text_parts.append(text)

        return {
            'success': True,
            'transcript': ' '.join(text_parts),
            'segments': seg_list,
            'engine': 'faster-whisper',
            'model': 'base',
            'language': info.language if info else language,
            'duration': round(info.duration, 2) if info else 0,
            'segment_count': len(seg_list),
        }
    except ImportError:
        return {'success': False, 'error': 'faster-whisper not installed'}
    except Exception as e:
        return {'success': False, 'error': f'faster-whisper failed: {e}'}


def _try_openai_whisper(audio_path: str, language: str) -> dict:
    """Attempt transcription with openai-whisper."""
    try:
        import whisper

        model = whisper.load_model('base')
        result = model.transcribe(audio_path, language=language)

        seg_list = []
        for seg in result.get('segments', []):
            text = seg.get('text', '').strip()
            if text:
                seg_list.append({
                    'start': round(seg.get('start', 0), 2),
                    'end': round(seg.get('end', 0), 2),
                    'text': text,
                })

        return {
            'success': True,
            'transcript': result.get('text', '').strip(),
            'segments': seg_list,
            'engine': 'openai-whisper',
            'model': 'base',
            'language': result.get('language', language),
            'segment_count': len(seg_list),
        }
    except ImportError:
        return {'success': False, 'error': 'openai-whisper not installed'}
    except Exception as e:
        return {'success': False, 'error': f'openai-whisper failed: {e}'}
