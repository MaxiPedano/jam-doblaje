"""Proceso aislado: diarización ligera y extracción de voces por hablante.

Subcomandos:
  install    descarga los modelos de hablante a la carpeta privada y escribe el marcador
  separate   diariza, separa las voces de las pistas y genera muestras escuchables
  remove     recombina las pistas quitando la voz elegida, sin volver a ejecutar IA

No usa shell ni código del usuario.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path

SAMPLE_SECONDS = 6.0     # duración de la muestra escuchable por hablante
FRAME = 0.25             # segundos por cuadro de análisis
EXCLUSIVE_RATIO = 1.41   # 3 dB por encima del otro hablante: cuadro exclusivo
BOTH_FACTOR = 3.0        # ambos fuertes respecto de su mediano: posible solape
PITCH_MIN = 50           # Hz: rango de tono de voz hablada
PITCH_MAX = 400
PITCH_REAL = 0.15        # fuerza de autocorrelación mínima para considerar habla
MIN_SEGMENT = 1.2        # segundos mínimos de una ventana para análisis de hablante
CLUSTER_DISTANCE = 0.55  # umbral coseno (distancia) para agrupar hablantes
STRATEGY = 'suma'        # 'suma' conserva fondo + voz elegida; 'resta' descuenta la quitada
MODELS = {2: 'speechbrain/sepformer-whamr16k', 3: 'speechbrain/sepformer-wsj03mix'}
ECAPA = 'speechbrain/spkrec-ecapa-voxceleb'


def speaker_ready(root: Path) -> bool:
    marker = root / 'speaker-model-ready.json'
    try:
        models = json.loads(marker.read_text(encoding='utf-8'))['models']
    except (OSError, KeyError, ValueError):
        return False
    base = root / 'models' / 'speakers'
    if any(not (base / name / 'hyperparams.yaml').is_file() for name in models):
        return False
    return all(importlib.util.find_spec(module)
               for module in ('torch', 'speechbrain', 'silero_vad', 'sklearn', 'soundfile'))


def install_models(root: Path):
    """Descarga SepFormer (2 y 3 voces) y ECAPA como archivos reales, sin symlinks."""
    import huggingface_hub
    base = root / 'models' / 'speakers'
    repos = sorted({*MODELS.values(), ECAPA})
    names = []
    for repo in repos:
        name = repo.split('/')[-1]
        names.append(name)
        huggingface_hub.snapshot_download(repo_id=repo, local_dir=str(base / name))
    (root / 'speaker-model-ready.json').write_text(json.dumps({'models': names}), encoding='utf-8')


def _db(signal) -> float:
    import numpy as np
    if not len(signal):
        return float('-inf')
    return 20 * np.log10(np.sqrt(float((signal ** 2).mean())) + 1e-12)


def _pitch(samples, sample_rate) -> tuple[float, int]:
    """Fuerza de autocorrelación (0..1) y tono dominante en Hz de un tramo de habla."""
    import numpy as np
    x = np.asarray(samples, dtype=np.float64)
    if len(x) < int(sample_rate * 0.1) or np.abs(x).max() < 1e-5:
        return 0.0, 0
    x = x - x.mean()
    limit = int(sample_rate * 0.05)
    autocorr = np.correlate(x, x, 'full')[len(x) - 1:][:limit]
    autocorr = autocorr / (autocorr[0] + 1e-12)
    low = max(1, int(sample_rate / PITCH_MAX))
    high = min(len(autocorr), int(sample_rate / PITCH_MIN))
    if high <= low:
        return 0.0, 0
    peak = low + int(np.argmax(autocorr[low:high]))
    return float(autocorr[peak]), int(round(sample_rate / peak))


def diarize(mono, sample_rate, root: Path) -> dict:
    """VAD Silero + embeddings ECAPA + agrupamiento AHC sobre la pista de voces."""
    import numpy as np
    import torch
    import torchaudio
    from silero_vad import get_speech_timestamps, load_silero_vad

    wav = torchaudio.transforms.Resample(sample_rate, 16000)(torch.from_numpy(np.ascontiguousarray(mono)))
    vad = load_silero_vad(onnx=False)
    stamps = get_speech_timestamps(wav, vad, sampling_rate=16000, min_speech_duration_ms=300,
                                   min_silence_duration_ms=300, speech_pad_ms=100)
    segments = [[round(s['start'] / 16000, 3), round(s['end'] / 16000, 3)] for s in stamps]
    windows = [segment for segment in segments if segment[1] - segment[0] >= MIN_SEGMENT]
    labels = list(range(len(windows)))
    n_clusters = 0 if len(windows) >= 2 else len(windows)
    if len(windows) >= 2:
        from sklearn.cluster import AgglomerativeClustering
        from speechbrain.inference.speaker import EncoderClassifier
        from speechbrain.utils.fetching import LocalStrategy

        model = EncoderClassifier.from_hparams(source=ECAPA, savedir=str(root / 'models' / 'speakers' / 'ecapa'),
                                               run_opts={'device': 'cpu'},
                                               local_strategy=LocalStrategy.COPY_SKIP_CACHE)
        embeds = []
        with torch.inference_mode():
            for start, end in windows:
                clip = wav[int(start * 16000):int(end * 16000)]
                if len(clip) > 48000:
                    best, best_rms = None, -1.0
                    for offset in range(0, len(clip) - 48000 + 1, 8000):
                        piece = clip[offset:offset + 48000]
                        rms = float((piece ** 2).mean())
                        if rms > best_rms:
                            best, best_rms = piece, rms
                    clip = best
                elif len(clip) < 8000:
                    clip = torch.nn.functional.pad(clip, (0, 8000 - len(clip)))
                emb = model.encode_batch(clip.unsqueeze(0)).squeeze().cpu().numpy()
                embeds.append(emb / (np.linalg.norm(emb) + 1e-9))
        clustering = AgglomerativeClustering(n_clusters=None, metric='cosine', linkage='average',
                                             distance_threshold=CLUSTER_DISTANCE)
        labels = clustering.fit_predict(np.stack(embeds)).tolist()
        n_clusters = len(set(labels))
    return {'segments': segments, 'windows': [[round(a, 3), round(b, 3)] for a, b in windows],
            'labels': [int(label) for label in labels], 'n_clusters': int(n_clusters)}


def _resample(samples, from_rate, to_rate, length):
    import numpy as np
    import torch
    import torchaudio.functional as AF
    out = AF.resample(torch.from_numpy(np.ascontiguousarray(samples)), from_rate, to_rate).numpy()
    if len(out) >= length:
        return out[:length]
    return np.pad(out, (0, length - len(out)))


def _separate_streams(mono, sample_rate, root: Path, n_speakers: int):
    import numpy as np
    import torch
    import torchaudio
    from speechbrain.inference.separation import SepformerSeparation
    from speechbrain.utils.fetching import LocalStrategy

    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    repo = MODELS[n_speakers]
    name = repo.split('/')[-1]
    model = SepformerSeparation.from_hparams(source=repo, savedir=str(root / 'models' / 'speakers' / name),
                                             run_opts={'device': 'cpu'},
                                             local_strategy=LocalStrategy.COPY_SKIP_CACHE)
    model_rate = int(model.hparams.sample_rate)
    batch = torch.from_numpy(np.ascontiguousarray(mono)).unsqueeze(0)
    if sample_rate != model_rate:
        batch = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=model_rate)(batch)
    with torch.inference_mode():
        estimated = model.separate_batch(batch)
    peak = estimated.abs().max()
    if float(peak) > 0:
        estimated = estimated / peak
    streams = [_resample(estimated[0, :, index].numpy(), model_rate, sample_rate, len(mono))
               for index in range(estimated.shape[-1])]
    return streams, name


def _frame_energies(streams, mono, sample_rate):
    import numpy as np
    hop = max(1, int(sample_rate * FRAME))
    n = min(len(mono), *(len(stream) for stream in streams)) // hop
    if n <= 0:
        raise ValueError('La pista de voces es demasiado corta para analizarla.')
    frames = [stream[:n * hop].reshape(n, hop) for stream in [*streams, mono]]
    energies = [np.sqrt((frame ** 2).mean(axis=1)) for frame in frames]
    return energies[:-1], energies[-1], n, hop


def _runs(indices) -> list[list[int]]:
    runs: list[list[int]] = []
    for index in indices:
        if runs and index == runs[-1][-1] + 1:
            runs[-1].append(int(index))
        else:
            runs.append([int(index)])
    return runs


def _best_sample(kept, other, ref_energy, sample_rate) -> int:
    """Inicio (en muestras) de la ventana de 6 s donde la voz elegida domina sobre la otra."""
    import numpy as np
    hop = max(1, int(sample_rate * FRAME))
    frames = max(1, int(SAMPLE_SECONDS / FRAME))
    n = min(len(kept), len(other), len(ref_energy)) // hop
    if n <= 0:
        return 0
    e_keep = np.sqrt((kept[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    e_other = np.sqrt((other[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    e_ref = ref_energy[:n * hop].reshape(n, hop).mean(axis=1)
    if n <= frames:
        return int(np.argmax(e_keep / (e_other + 1e-9))) * hop
    kernel = np.ones(frames) / frames
    mean_keep = np.convolve(e_keep, kernel, 'valid')
    mean_other = np.convolve(e_other, kernel, 'valid')
    mean_ref = np.convolve(e_ref, kernel, 'valid')
    scores = np.log(mean_keep + 1e-9) - np.log(mean_other + 1e-9)
    scores[mean_ref < np.percentile(e_ref, 50)] = -np.inf
    if not np.isfinite(scores).any():
        scores = np.log(mean_keep + 1e-9)
    return int(np.argmax(scores)) * hop


def run_separate(stems: Path, root: Path):
    import numpy as np
    import soundfile as sf

    vocals_path = stems / 'vocals.wav'
    if not vocals_path.is_file():
        raise ValueError('Este trabajo no tiene pistas separadas. Eliminálo y volvé a cargar el video.')
    vocals, sample_rate = sf.read(vocals_path, dtype='float32', always_2d=True)
    mono = vocals.mean(axis=1)
    if not len(mono):
        raise ValueError('La pista de voces está vacía.')

    diar = diarize(mono, sample_rate, root)
    if diar['n_clusters'] == 1:
        # A single detected speaker needs no second neural separation pass.
        streams, model_name = [mono], 'single-speaker-fast-path'
        n_speakers = 1
    else:
        n_speakers = 3 if diar['n_clusters'] == 3 else 2
        streams, model_name = _separate_streams(mono, sample_rate, root, n_speakers)

    energies, ref_energy, n_frames, hop = _frame_energies(streams, mono, sample_rate)
    ref_active = ref_energy > np.percentile(ref_energy, 50)
    total_power = sum(float((energy ** 2).sum()) for energy in energies)
    both_strong = 0
    voices = []
    for index, stream in enumerate(streams, start=1):
        own = energies[index - 1]
        other_energies = [energy for k, energy in enumerate(energies, start=1) if k != index]
        others = np.mean(other_energies, axis=0) if other_energies else np.zeros_like(own)
        exclusive = ref_active & (own > others * EXCLUSIVE_RATIO)
        if len(streams) == 2:
            other = energies[2 - index]
            both_strong += int((ref_active & (own > np.median(own) * BOTH_FACTOR)
                                & (other > np.median(other) * BOTH_FACTOR)).sum())
        pitch_strength, pitch_hz = 0.0, 0
        exclusive_indices = np.where(exclusive)[0]
        for run in _runs(exclusive_indices):
            if len(run) < 2:
                continue
            start = run[0] * hop
            strength, hz = _pitch(stream[start:start + min(len(run) * hop, int(1.2 * sample_rate))], sample_rate)
            if strength > pitch_strength:
                pitch_strength, pitch_hz = strength, hz
        if pitch_strength < PITCH_REAL and len(exclusive_indices):
            # sin tramos seguidos: tono por cuadro sobre los cuadros exclusivos más fuertes
            ranked = sorted(exclusive_indices, key=lambda frame: own[frame], reverse=True)[:6]
            frame_scores = [_pitch(stream[frame * hop:frame * hop + hop], sample_rate) for frame in ranked]
            strengths = [score[0] for score in frame_scores]
            pitch_strength = float(np.median(strengths))
            pitch_hz = int(frame_scores[int(np.argmax(strengths))][1]) if pitch_strength >= PITCH_REAL else 0
        voices.append({
            'stream': index,
            'energy_db': round(_db(stream), 1),
            'share': round(float((own ** 2).sum()) / (total_power + 1e-12), 3),
            'exclusive_pct': round(float(exclusive.sum()) / max(int(ref_active.sum()), 1) * 100, 1),
            'pitch_hz': int(pitch_hz),
            'pitch_strength': round(float(pitch_strength), 2),
        })

    both_pct = round(both_strong / max(n_frames, 1) * 100, 1)
    real = [voice for voice in voices if voice['pitch_strength'] >= PITCH_REAL]
    warnings = []
    if both_pct > 25.0:
        warnings.append('Hay tramos donde las dos voces suenan a la vez: la separación puede quedar con restos.')
    if len(real) < 2:
        warnings.append('No encontré una segunda voz clara. Si solo querés recortar partes, usá el modo de diálogo.')

    stems.mkdir(parents=True, exist_ok=True)
    window = int(SAMPLE_SECONDS * sample_rate)
    for index, stream in enumerate(streams, start=1):
        sf.write(stems / f'speaker-{index}.wav', stream, sample_rate, subtype='PCM_16')
        other_streams = [data for k, data in enumerate(streams, start=1) if k != index]
        others = np.mean(other_streams, axis=0) if other_streams else np.zeros_like(stream)
        start = _best_sample(stream, others, ref_energy, sample_rate)
        sample = stream[start:start + window]
        if not len(sample):
            sample = stream[:window]
        sf.write(stems / f'sample-{index}.wav', sample, sample_rate, subtype='PCM_16')

    summary = {'model': model_name, 'n_speakers': n_speakers, 'n_voices': len(real),
               'diarization': diar, 'voices': voices, 'both_strong_pct': both_pct,
               'warnings': warnings, 'strategy': STRATEGY}
    (stems / 'speakers.json').write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding='utf-8')


def run_remove(stems: Path, target: int, strategy: str, destination: Path):
    import numpy as np
    import soundfile as sf

    vocals, sample_rate = sf.read(stems / 'vocals.wav', dtype='float32', always_2d=True)
    background, _ = sf.read(stems / 'background.wav', dtype='float32', always_2d=True)
    stream_paths = sorted(stems.glob('speaker-*.wav'))
    if len(stream_paths) < 1:
        raise ValueError('Este trabajo no tiene voces separadas. Eliminálo y volvé a cargar el video.')
    streams = {}
    for path in stream_paths:
        number = int(path.stem.split('-')[1])
        data, rate = sf.read(path, dtype='float32', always_2d=False)
        if rate != sample_rate:
            raise ValueError('Las voces guardadas no coinciden con las pistas. Eliminá el trabajo y volvé a cargarlo.')
        streams[number] = data
    if target not in streams:
        raise ValueError('La voz indicada no existe en este trabajo.')
    length = min(len(vocals), len(background), *(len(data) for data in streams.values()))
    vocals, background = vocals[:length], background[:length]
    removed = streams[target][:length]
    if removed.ndim == 1:
        removed = np.stack([removed] * 2, axis=1)
    if strategy == 'resta':
        output = (vocals + background) - removed
    else:
        output = background.copy()
        for number, data in sorted(streams.items()):
            if number == target:
                continue
            data = data[:length]
            if data.ndim == 1:
                data = np.stack([data] * 2, axis=1)
            output = output + data
    if len(output):
        peak = float(abs(output).max())
        if peak > 0.99:
            output = output * (0.99 / peak)
    sf.write(destination, output.astype(np.float32), sample_rate, subtype='PCM_16')


def remove_voice(root: Path, job_id: str, target: int, strategy: str = STRATEGY):
    """Recombina las pistas quitando una voz y genera el video. Sin IA."""
    from .processing import failure, mux, stem_duration, store_settings, update

    folder = root / 'jobs' / job_id
    log = folder / 'processing.log'
    stems = folder / 'stems'
    try:
        if not (folder / 'original').is_file():
            raise ValueError('El original no está disponible. Eliminá el trabajo y volvé a cargarlo.')
        if not (stems / 'speakers.json').is_file():
            raise ValueError('Este trabajo no tiene voces separadas. Eliminálo y volvé a cargar el video.')
        seconds = stem_duration(stems)
        update(root, job_id, 'processing', 15, 'Combinando las voces…', seconds)
        mixed = folder / 'mixed.wav'
        run_remove(stems, target, strategy, mixed)
        update(root, job_id, 'processing', 85, 'Creando el video…', seconds)
        mux(folder, seconds, mixed, log)
        message = f'Se quitó la voz {target}. Escuchá el resultado comparado con el original.'
        store_settings(root, job_id, 'voz', '', 'ready', 100, message, seconds)
    except Exception as error:
        if (folder / 'processed.mp4').is_file():
            failure(root, job_id, error, keep_previous=True)
        else:
            detail = str(error) if isinstance(error, ValueError) else 'Revisá processing.log en la carpeta privada del trabajo.'
            update(root, job_id, 'voices', 100, f'No se pudo quitar la voz: {detail}')
    finally:
        (folder / 'mixed.wav').unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Voces por hablante de Doblaje Studio')
    sub = parser.add_subparsers(dest='command', required=True)
    install = sub.add_parser('install')
    install.add_argument('root', type=Path)
    separate = sub.add_parser('separate')
    separate.add_argument('stems', type=Path)
    separate.add_argument('root', type=Path)
    remove = sub.add_parser('remove')
    remove.add_argument('stems', type=Path)
    remove.add_argument('target', type=int)
    remove.add_argument('destination', type=Path)
    remove.add_argument('--strategy', choices=['suma', 'resta'], default=STRATEGY)
    args = parser.parse_args()
    if args.command == 'install':
        install_models(args.root)
        print('Modelos de voces instalados.')
    elif args.command == 'separate':
        run_separate(args.stems, args.root)
        print('Voces separadas y muestras listas.')
    else:
        run_remove(args.stems, args.target, args.strategy, args.destination)
        print('Mezcla generada.')


if __name__ == '__main__':
    main()
