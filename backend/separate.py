"""Proceso aislado: separa voces del resto y aplica máscara por tramos de diálogo.

No usa shell ni código del usuario. Si existen las pistas guardadas en `--stems`,
se reutilizan sin volver a ejecutar el modelo.
"""
import argparse
import json
import os
from pathlib import Path

MERGE_GAP = 0.15        # segundos: tramos casi pegados se unen antes de enmascarar
RAMP = 0.06             # segundos de fundido al entrar y salir de un tramo
HOP = 0.05              # paso del análisis de nivel
WIN = 0.10              # ventana del análisis de nivel
MIN_SEGMENT = 0.25      # tramos detectados mínimos
DETECT_MERGE_GAP = 0.30 # segundos: pausas cortes que se consideran parte del mismo tramo
DYNAMIC_RANGE = 22      # dB bajo el pico de voz para considerar tramo de diálogo
ABS_FLOOR = -60.0       # dB: por debajo se considera silencio


def stems_paths(stems: Path) -> tuple[Path, Path]:
    return stems / 'vocals.wav', stems / 'background.wav'


def detect_dialogue(vocals, sample_rate) -> list[list[float]]:
    """Tramos donde la energía vocal es alta (diálogo principal probable)."""
    import numpy as np
    hop, win = int(sample_rate * HOP), int(sample_rate * WIN)
    mono = vocals.mean(axis=1)
    if len(mono) < win:
        return []
    frames = np.lib.stride_tricks.sliding_window_view(mono, win)[::hop]
    if not len(frames):
        return []
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-12)
    threshold = max(float(db.max()) - DYNAMIC_RANGE, ABS_FLOOR)
    active = db > threshold
    segments: list[list[int]] = []
    start = None
    for index, on in enumerate(active):
        if on and start is None:
            start = index
        elif not on and start is not None:
            segments.append([start, index])
            start = None
    if start is not None:
        segments.append([start, len(active)])
    merge_frames = round(DETECT_MERGE_GAP / HOP)
    merged: list[list[int]] = []
    for segment in segments:
        if merged and segment[0] - merged[-1][1] <= merge_frames:
            merged[-1][1] = segment[1]
        else:
            merged.append(segment)
    return [[round(a * HOP, 3), round(b * HOP, 3)] for a, b in merged if (b - a) * HOP >= MIN_SEGMENT]


def gain_for(ranges: list[list[float]], samples: int, sample_rate: int):
    import numpy as np
    gain = np.ones(samples, dtype=np.float32)
    if samples <= 0:
        return gain
    ordered = sorted(([max(0.0, float(a)), min(samples / sample_rate, float(b))] for a, b in ranges if b > a),
                     key=lambda item: item[0])
    merged: list[list[float]] = []
    for start, end in ordered:
        if end <= start:
            continue
        if merged and start - merged[-1][1] <= MERGE_GAP:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    ramp = int(RAMP * sample_rate)
    for start, end in merged:
        a, b = int(start * sample_rate), min(samples, int(end * sample_rate))
        if b <= a:
            continue
        gain[a:b] = 0
        fade_out = min(ramp, a)
        if fade_out:
            gain[a - fade_out:a] = np.linspace(1, 0, fade_out, dtype=np.float32)
        fade_in = min(ramp, samples - b)
        if fade_in:
            gain[b:b + fade_in] = np.linspace(0, 1, fade_in, dtype=np.float32)
    return gain


def separate(source: Path, root: Path, stems: Path | None):
    """Ejecuta Demucs y devuelve (vocals, background, sample_rate); guarda las pistas si hay carpeta."""
    os.environ['TORCH_HOME'] = str(root / 'models')
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    model = get_model('htdemucs')
    model.cpu().eval()
    data, sample_rate = sf.read(source, dtype='float32', always_2d=True)
    if sample_rate != model.samplerate or data.shape[1] != model.audio_channels:
        raise ValueError('El audio debe ser estéreo a 44100 Hz.')
    waveform = torch.from_numpy(data.T.copy())
    reference = waveform.mean(0)
    mean = reference.mean()
    std = reference.std()
    if std < 1e-8:
        vocals = data * 0
        background = data
    else:
        normalized = (waveform - mean) / std
        with torch.inference_mode():
            sources = apply_model(model, normalized[None], device='cpu', shifts=1, split=True, overlap=0.25, progress=True)[0]
        sources = sources * std + mean
        vocals_index = model.sources.index('vocals')
        vocals = sources[vocals_index].T.numpy()
        # Sumar las pistas no vocales evita reintroducir la voz original mediante una resta imperfecta.
        background = sources[[i for i in range(len(model.sources)) if i != vocals_index]].sum(0).T.numpy()
    peak = max(float(abs(vocals).max()), float(abs(background).max()), 1e-9)
    if peak > 0.99:
        vocals = vocals * (0.99 / peak)
        background = background * (0.99 / peak)
    if stems is not None:
        vocals_path, background_path = stems_paths(stems)
        stems.mkdir(parents=True, exist_ok=True)
        sf.write(vocals_path, vocals, sample_rate, subtype='PCM_16')
        sf.write(background_path, background, sample_rate, subtype='PCM_16')
    return vocals, background, sample_rate


def run(source: Path, destination: Path, root: Path, ranges_file: Path | None = None,
        detect: bool = False, stems: Path | None = None):
    import soundfile as sf

    vocals, background, sample_rate = None, None, None
    if stems is not None:
        vocals_path, background_path = stems_paths(stems)
        if vocals_path.is_file() and background_path.is_file():
            vocals, sample_rate = sf.read(vocals_path, dtype='float32', always_2d=True)
            background, rate = sf.read(background_path, dtype='float32', always_2d=True)
            if rate != sample_rate or len(background) != len(vocals):
                raise ValueError('Las pistas guardadas no coinciden. Eliminá el trabajo y volvé a cargarlo.')
    if vocals is None:
        vocals, background, sample_rate = separate(source, root, stems)

    ranges: list[list[float]] = []
    if ranges_file is not None:
        ranges = json.loads(ranges_file.read_text(encoding='utf-8'))
    elif detect:
        ranges = detect_dialogue(vocals, sample_rate)
        if stems is not None:
            (stems / 'detected-ranges.json').write_text(json.dumps(ranges), encoding='utf-8')

    if ranges:
        gain = gain_for(ranges, len(vocals), sample_rate)
        output = background + vocals * gain[:, None]
    else:
        output = background
    if len(output):
        peak = float(abs(output).max())
        if peak > 0.99:
            output = output * (0.99 / peak)
    sf.write(destination, output, sample_rate, subtype='PCM_16')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('root', type=Path)
    parser.add_argument('--stems', type=Path, default=None)
    parser.add_argument('--ranges', type=Path, default=None)
    parser.add_argument('--detect', action='store_true')
    args = parser.parse_args()
    run(args.source, args.destination, args.root, ranges_file=args.ranges, detect=args.detect, stems=args.stems)
