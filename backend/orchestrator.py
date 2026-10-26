"""Perfilado y selección del pipeline de procesamiento.

No ejecuta shell dinámico ni procesa archivos por sí mismo. Devuelve datos
estructurados para que ``processing.py`` conserve la ejecución segura por
listas de argumentos y la cola de un solo worker.
"""
from dataclasses import dataclass
import re
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class MediaProfile:
    duration: float
    has_video: bool
    has_audio: bool
    video_codec: str | None
    audio_codec: str | None
    audio_channels: str | None
    audio_sample_rate: int | None


@dataclass(frozen=True)
class ProcessingPlan:
    mode: str
    stages: tuple[str, ...]
    demucs_model: str
    speaker_model: str | None
    audio_format: str
    prefer_video_copy: bool

    @property
    def description(self) -> str:
        if self.mode == 'voz':
            return 'Demucs + selección automática de hablantes'
        if self.mode == 'dialogo':
            return 'Demucs + máscara por tramos'
        return 'Demucs + eliminación de voces'


_DURATION = re.compile(rb'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)')
_VIDEO = re.compile(r'\bVideo:\s*([^,\s]+)', re.IGNORECASE)
_AUDIO = re.compile(r'\bAudio:\s*([^,\s]+)', re.IGNORECASE)
_RATE = re.compile(r'\b(\d{4,6})\s*Hz\b', re.IGNORECASE)
_CHANNELS = re.compile(r'\b(mono|stereo|\d+\.\d+)\b', re.IGNORECASE)


def _duration(stderr: bytes) -> float:
    match = _DURATION.search(stderr)
    if not match:
        return 0.0
    return sum(float(value) * factor for value, factor in zip(match.groups(), (3600, 60, 1)))


def probe_media(binary: str, source: Path, input_options: list[str], timeout: int = 120) -> MediaProfile:
    """Extrae metadatos con FFmpeg y valida que haya una pista de video."""
    result = subprocess.run(
        [binary, '-nostdin', '-hide_banner', *input_options, '-i', str(source),
         '-map', '0:v:0', '-frames:v', '1', '-f', 'null', '-'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ValueError('El video no pudo validarse con FFmpeg.')

    text = result.stderr.decode('utf-8', errors='replace')
    video = _VIDEO.search(text)
    audio = _AUDIO.search(text)
    rate = _RATE.search(text)
    channels = _CHANNELS.search(audio.group(0)) if audio else None
    return MediaProfile(
        duration=_duration(result.stderr),
        has_video=video is not None,
        has_audio=audio is not None,
        video_codec=video.group(1).lower() if video else None,
        audio_codec=audio.group(1).lower() if audio else None,
        audio_channels=channels.group(1).lower() if channels else None,
        audio_sample_rate=int(rate.group(1)) if rate else None,
    )


def build_plan(mode: str, profile: MediaProfile) -> ProcessingPlan:
    """Elige el pipeline barato y seguro según el modo solicitado."""
    if mode not in {'dialogo', 'voces', 'voz'}:
        raise ValueError(f'Modo de procesamiento desconocido: {mode}.')
    if not profile.has_video:
        raise ValueError('El archivo no contiene una pista de video.')
    if not profile.has_audio:
        raise ValueError('El video debe contener una pista de audio.')

    if mode == 'voz':
        stages = ('demucs', 'speaker-auto')
        speaker_model = 'auto: ECAPA/VAD → SepFormer 2 o 3 voces'
    elif mode == 'dialogo':
        stages = ('demucs', 'dialogue-mask')
        speaker_model = None
    else:
        stages = ('demucs', 'remove-vocals')
        speaker_model = None
    return ProcessingPlan(mode, stages, 'htdemucs', speaker_model,
                          'stereo/44100 PCM16', prefer_video_copy=True)
