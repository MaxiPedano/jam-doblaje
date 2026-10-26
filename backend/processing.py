import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import wave

from .config import MAX_SECONDS, MODEL
from .db import connect
from .orchestrator import build_plan, probe_media

INPUT_OPTIONS = ['-protocol_whitelist', 'file,pipe', '-format_whitelist', 'mov,matroska,webm,avi']
MAX_RANGES = 60


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def model_ready(root: Path) -> bool:
    marker = root / 'model-ready.json'
    try:
        return (json.loads(marker.read_text())['model'] == MODEL
                and any((root / 'models').rglob('*.th'))
                and all(importlib.util.find_spec(module) for module in ('torch', 'demucs', 'soundfile')))
    except (OSError, KeyError, ValueError, ImportError):
        return False


def update(root: Path, job_id: str, status: str, progress: int, message: str, seconds=None):
    with connect(root) as db:
        db.execute('UPDATE jobs SET status=?,progress=?,message=?,seconds=COALESCE(?,seconds) WHERE id=?',
                   (status, progress, message, seconds, job_id))


def execute(args: list[str], log: Path, timeout: int):
    with log.open('ab') as output:
        subprocess.run(args, stdout=output, stderr=output, timeout=timeout, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def _seconds(token: str) -> float:
    text = token.strip()
    if not text:
        raise ValueError('Hay un tramo vacío. Usá inicio-fin, por ejemplo 0:06-0:29.')
    if ':' in text:
        parts = text.split(':')
        if len(parts) > 3:
            raise ValueError(f'El tramo “{token}” no es válido.')
        try:
            values = [float(part) for part in parts]
        except ValueError:
            raise ValueError(f'El tramo “{token}” no es válido. Usá mm:ss, por ejemplo 0:06-0:29.')
        total = 0.0
        for value in values:
            total = total * 60 + value
    else:
        try:
            total = float(text)
        except ValueError:
            raise ValueError(f'El tramo “{token}” no es válido. Usá mm:ss, por ejemplo 0:06-0:29.')
    if not 0 <= total <= MAX_SECONDS + 1:
        raise ValueError(f'Los tramos deben estar entre 0:00 y {MAX_SECONDS // 60}:00.')
    return total


def parse_ranges_text(text: str) -> list[list[float]]:
    """'0:06-0:29, 1:02.5-1:10' o '6-29' -> [[6.0, 29.0], ...]"""
    cleaned = (text or '').replace('\r', ',').replace(';', ',').replace('\n', ',')
    pieces = [piece.strip() for piece in cleaned.split(',') if piece.strip()]
    if not pieces:
        return []
    if len(pieces) > MAX_RANGES:
        raise ValueError(f'Podés marcar hasta {MAX_RANGES} tramos.')
    ranges = []
    for piece in pieces:
        normalized = piece.replace('–', '-').replace('—', '-')
        if normalized.count('-') != 1:
            raise ValueError(f'El tramo “{piece}” debe ser inicio-fin, por ejemplo 0:06-0:29.')
        start_text, end_text = normalized.split('-')
        start, end = _seconds(start_text), _seconds(end_text)
        if end <= start:
            raise ValueError(f'En el tramo “{piece}” el fin debe ser mayor que el inicio.')
        ranges.append([round(start, 3), round(end, 3)])
    return ranges


def stamp(value: float) -> str:
    minutes, seconds = divmod(max(0.0, value), 60)
    body = f'{seconds:.2f}'.rstrip('0').rstrip('.')
    body = body.zfill(4) if '.' in body else body.zfill(2)
    return f'{int(minutes)}:{body}'


def format_ranges(ranges: list[list[float]]) -> str:
    return ', '.join(f'{stamp(start)}-{stamp(end)}' for start, end in ranges)


def in_duration(ranges: list[list[float]], seconds: float) -> list[list[float]]:
    kept = [[round(start, 3), round(min(end, seconds), 3)] for start, end in ranges if start < seconds]
    return [[start, end] for start, end in kept if end > start]


def stem_duration(stems: Path) -> float:
    with wave.open(str(stems / 'background.wav')) as audio:
        return audio.getnframes() / audio.getframerate()


def mux(folder: Path, seconds: float, audio: Path, log: Path):
    output = folder / 'processed.mp4'
    copied = folder / 'processed-copy.mp4'
    copy_args = [ffmpeg(), '-nostdin', '-y', '-v', 'error', *INPUT_OPTIONS, '-i', str(folder / 'original'),
                 '-i', str(audio), '-map', '0:v:0', '-map', '1:a:0', '-t', str(seconds),
                 '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart',
                 '-map_metadata', '-1', str(copied)]
    try:
        execute(copy_args, log, 1800)
        os.replace(copied, output)
        return
    except Exception:
        copied.unlink(missing_ok=True)
    execute([ffmpeg(), '-nostdin', '-y', '-v', 'error', *INPUT_OPTIONS, '-i', str(folder / 'original'),
             '-i', str(audio), '-map', '0:v:0', '-map', '1:a:0', '-t', str(seconds),
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-map_metadata', '-1',
             str(output)], log, 1800)


def job_settings(root: Path, job_id: str) -> tuple[str, str]:
    with connect(root) as db:
        row = db.execute('SELECT modo, ranges FROM jobs WHERE id=?', (job_id,)).fetchone()
    if not row:
        raise ValueError('El trabajo no existe.')
    return (row['modo'] or 'voces'), (row['ranges'] or '').strip()


def store_settings(root: Path, job_id: str, modo: str, ranges: str, status: str, progress: int, message: str, seconds=None):
    with connect(root) as db:
        db.execute('UPDATE jobs SET modo=?,ranges=?,status=?,progress=?,message=?,seconds=COALESCE(?,seconds) WHERE id=?',
                   (modo, ranges, status, progress, message, seconds, job_id))


def failure(root: Path, job_id: str, error: Exception, keep_previous=False):
    if isinstance(error, ValueError):
        message = str(error)
    elif isinstance(error, subprocess.TimeoutExpired):
        message = 'El procesamiento superó el tiempo máximo. Probá un fragmento más corto.'
    else:
        message = 'No se pudo procesar. Verificá que sea un video con audio compatible. El equipo puede revisar processing.log en la carpeta privada del trabajo.'
    if keep_previous and (root / 'jobs' / job_id / 'processed.mp4').is_file():
        update(root, job_id, 'ready', 100, f'No se pudo ajustar: {message} Se conserva el resultado anterior.')
        return
    update(root, job_id, 'failed', 0, message)
    (root / 'jobs' / job_id / 'processed.mp4').unlink(missing_ok=True)


def process(root: Path, job_id: str):
    folder = root / 'jobs' / job_id
    log = folder / 'processing.log'
    try:
        modo, ranges_text = job_settings(root, job_id)
        update(root, job_id, 'processing', 10, 'Perfilando el video y preparando el pipeline…')
        binary = ffmpeg()
        # Solo contenedores de video locales: rechaza playlists y fuentes de red.
        profile = probe_media(binary, folder / 'original', INPUT_OPTIONS)
        plan = build_plan(modo, profile)
        total = profile.duration
        if not 0 < total <= MAX_SECONDS:
            raise ValueError(f'El video debe tener una duración válida de hasta {MAX_SECONDS // 60} minutos.')
        with log.open('ab') as output:
            output.write((f'orchestrator: {plan.description}; stages={plan.stages}; '
                          f'video={profile.video_codec}; audio={profile.audio_codec}; '
                          f'rate={profile.audio_sample_rate}; channels={profile.audio_channels}\n').encode())
        execute([binary, '-nostdin', '-y', '-v', 'error', *INPUT_OPTIONS, '-i', str(folder / 'original'),
                 '-t', str(MAX_SECONDS + 1), '-map', '0:a:0', '-vn', '-ac', '2', '-ar', '44100',
                 '-c:a', 'pcm_s16le', str(folder / 'audio.wav')], log, 300)
        with wave.open(str(folder / 'audio.wav')) as audio:
            seconds = audio.getnframes() / audio.getframerate()
        if seconds <= 0 or seconds > MAX_SECONDS:
            raise ValueError(f'El video debe tener audio y durar como máximo {MAX_SECONDS // 60} minutos.')
        update(root, job_id, 'processing', 30, f'{plan.description}. Puede tardar varios minutos…', seconds)
        stems = folder / 'stems'
        mixed = folder / 'mixed.wav'
        args = [sys.executable, '-m', 'backend.separate', str(folder / 'audio.wav'), str(mixed), str(root),
                '--stems', str(stems)]
        auto = False
        if modo == 'dialogo':
            if ranges_text:
                ranges = in_duration(parse_ranges_text(ranges_text), seconds)
                if not ranges:
                    raise ValueError('Los tramos marcados quedan fuera de la duración del video.')
                ranges_file = folder / 'ranges.json'
                ranges_file.write_text(json.dumps(ranges), encoding='utf-8')
                args += ['--ranges', str(ranges_file)]
            else:
                auto = True
                args += ['--detect']
        execute(args, log, 7200)
        stored = ranges_text
        if auto:
            detected = json.loads((stems / 'detected-ranges.json').read_text(encoding='utf-8'))
            stored = format_ranges(in_duration(detected, seconds))
        if modo == 'voz':
            update(root, job_id, 'processing', 60, 'Separando cada hablante. Puede tardar varios minutos…', seconds)
            execute([sys.executable, '-m', 'backend.speakers', 'separate', str(stems), str(root)], log, 7200)
            store_settings(root, job_id, modo, '', 'voices', 100,
                           'Escuchá cada voz y elegí cuál quitar del video.', seconds)
            return
        update(root, job_id, 'processing', 80, 'Creando el video con el audio procesado…', seconds)
        mux(folder, seconds, mixed, log)
        message = 'Video procesado. Compará el resultado antes de usarlo.'
        if modo == 'dialogo':
            message = (f'Se recortó el diálogo en {len(parse_ranges_text(stored))} tramos: {stored}. Escuchá y ajustá si hace falta.'
                       if stored else 'No se detectó diálogo fuerte. Marcá los tramos manualmente para revisar.')
        store_settings(root, job_id, modo, stored, 'ready', 100, message, seconds)
    except Exception as error:
        failure(root, job_id, error)
    finally:
        for name in ('audio.wav', 'mixed.wav', 'ranges.json'):
            (folder / name).unlink(missing_ok=True)
        with connect(root) as db:
            row = db.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row and row['status'] != 'ready':
            (folder / 'processed.mp4').unlink(missing_ok=True)


def remix(root: Path, job_id: str, modo: str, ranges_text: str):
    """Recombina las pistas ya separadas con nuevos tramos, sin volver a ejecutar el modelo."""
    folder = root / 'jobs' / job_id
    log = folder / 'processing.log'
    try:
        vocals = folder / 'stems' / 'vocals.wav'
        background = folder / 'stems' / 'background.wav'
        if not vocals.is_file() or not background.is_file():
            raise ValueError('Este trabajo no tiene pistas separadas. Eliminálo y volvé a cargar el video.')
        if not (folder / 'original').is_file():
            raise ValueError('El original no está disponible. Eliminá el trabajo y volvé a cargarlo.')
        seconds = stem_duration(folder / 'stems')
        update(root, job_id, 'processing', 10, 'Mezclando las pistas guardadas…', seconds)
        stems = folder / 'stems'
        mixed = folder / 'mixed.wav'
        args = [sys.executable, '-m', 'backend.separate', str(vocals), str(mixed), str(root), '--stems', str(stems)]
        ranges_text = (ranges_text or '').strip()
        auto = False
        if modo == 'dialogo':
            if ranges_text:
                ranges = in_duration(parse_ranges_text(ranges_text), seconds)
                if not ranges:
                    raise ValueError('Los tramos marcados quedan fuera de la duración del video.')
                ranges_file = folder / 'ranges.json'
                ranges_file.write_text(json.dumps(ranges), encoding='utf-8')
                args += ['--ranges', str(ranges_file)]
            else:
                auto = True
                args += ['--detect']
        execute(args, log, 1800)
        stored = ranges_text
        if auto:
            detected = json.loads((stems / 'detected-ranges.json').read_text(encoding='utf-8'))
            stored = format_ranges(in_duration(detected, seconds))
        update(root, job_id, 'processing', 80, 'Actualizando el video…', seconds)
        mux(folder, seconds, mixed, log)
        message = 'Video actualizado con los tramos indicados.'
        if modo == 'dialogo':
            message = (f'Se recortó el diálogo en {len(parse_ranges_text(stored))} tramos: {stored}. Escuchá y ajustá si hace falta.'
                       if stored else 'No se detectó diálogo fuerte. Marcá los tramos manualmente para revisar.')
        store_settings(root, job_id, modo, stored, 'ready', 100, message, seconds)
    except Exception as error:
        failure(root, job_id, error, keep_previous=True)
    finally:
        for name in ('mixed.wav', 'ranges.json'):
            (folder / name).unlink(missing_ok=True)
