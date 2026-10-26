import secrets
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from .app import COOKIE, create_app
from .auth import password_hash, token_hash
from .config import MAX_UPLOAD
from .db import connect, initialize
from .processing import format_ranges, parse_ranges_text, process, remix

HEADERS = {'X-Doblaje-Request': 'studio', 'Origin': 'http://localhost:5173'}


def write_stereo(path: Path, seconds=1.0, sample_rate=44100):
    import math
    import struct
    import wave
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        frames = int(seconds * sample_rate)
        out.writeframes(b''.join(struct.pack('<hh', value, value) for value in
                                 (int(3000 * math.sin(index / 40)) for index in range(frames))))


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='doblaje-tests-')
        self.root = Path(self.temp.name)
        self.removed = []
        self.client = TestClient(create_app(self.root, runner=lambda *_: None, ready_check=lambda _: True,
                                             remix_runner=lambda *_: None, speaker_ready_check=lambda _: True,
                                             remove_runner=lambda *args: self.removed.append(args)))
        self.client.__enter__()
        self.token = secrets.token_urlsafe(32)
        (self.root / 'setup-token').write_text(self.token, encoding='utf-8')
        self.credentials = {'username': 'equipo', 'password': secrets.token_urlsafe(20)}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def setup_account(self):
        response = self.client.post('/api/studio/setup', json={**self.credentials, 'token': self.token}, headers=HEADERS)
        self.assertEqual(response.status_code, 201, response.text)
        return response

    def upload(self, body=b'video-de-prueba', modo: str | None = None):
        url = '/api/studio/jobs' + (f'?modo={modo}' if modo else '')
        return self.client.post(url, content=body, headers={**HEADERS, 'X-File-Name': 'prueba.mp4'})

    def synthetic_video(self, seconds=1) -> bytes:
        from .processing import ffmpeg
        with tempfile.TemporaryDirectory() as sample:
            path = Path(sample) / 'sample.mp4'
            subprocess.run([ffmpeg(), '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=24',
                            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', str(seconds),
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)],
                           check=True, timeout=120)
            return path.read_bytes()

    def test_setup_login_session_expiration_and_logout(self):
        self.assertEqual(self.client.get('/api/studio/jobs').status_code, 401)
        response = self.setup_account()
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertNotIn('password', response.json())
        self.assertEqual(self.client.get('/api/studio/me').json()['role'], 'admin')
        self.assertEqual(self.client.post('/api/studio/setup', json={**self.credentials, 'token': self.token}, headers=HEADERS).status_code, 409)
        self.client.post('/api/studio/logout', headers=HEADERS)
        self.assertEqual(self.client.get('/api/studio/me').status_code, 401)
        self.assertEqual(self.client.post('/api/studio/login', json={**self.credentials, 'password': 'incorrect-password'}, headers=HEADERS).status_code, 401)
        self.assertEqual(self.client.post('/api/studio/login', json=self.credentials, headers=HEADERS).status_code, 200)
        with connect(self.root) as db:
            db.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.client.get('/api/studio/me').status_code, 401)

    def test_csrf_bootstrap_token_and_subscriber_permissions(self):
        payload = {**self.credentials, 'token': self.token}
        self.assertEqual(self.client.post('/api/studio/setup', json=payload).status_code, 403)
        self.assertEqual(self.client.post('/api/studio/setup', json=payload, headers={**HEADERS, 'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/studio/setup', json={**payload, 'token': 'x' * 32}, headers=HEADERS).status_code, 403)
        self.setup_account()
        with connect(self.root) as db:
            db.execute("UPDATE users SET role='subscriber'")
        self.assertEqual(self.upload().status_code, 403)
        self.assertEqual(self.client.get('/api/studio/jobs').status_code, 403)

    def test_upload_limits_capacity_and_private_download_ranges(self):
        self.setup_account()
        response = self.client.post('/api/studio/jobs', content=b'a', headers={**HEADERS, 'X-File-Name': 'malware.exe'})
        self.assertEqual(response.status_code, 415)
        response = self.client.post('/api/studio/jobs', content=b'a', headers={**HEADERS, 'X-File-Name': 'a.mp4', 'Content-Length': str(MAX_UPLOAD + 1)})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.upload(b'').status_code, 400)
        first = self.upload()
        self.assertEqual(first.status_code, 202, first.text)
        job = first.json()['id']
        self.assertEqual(self.client.get(f'/api/studio/jobs/{job}/media/processed').status_code, 409)
        self.assertEqual(self.client.delete(f'/api/studio/jobs/{job}', headers=HEADERS).status_code, 409)
        self.upload(); self.upload()
        self.assertEqual(self.upload().status_code, 409)
        (self.root / 'jobs' / job / 'processed.mp4').write_bytes(b'0123456789')
        with connect(self.root) as db:
            db.execute("UPDATE jobs SET status='ready' WHERE id=?", (job,))
        response = self.client.get(f'/api/studio/jobs/{job}/media/processed', headers={'Range': 'bytes=2-5'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b'2345')
        self.assertEqual(self.client.get(f'/api/studio/jobs/{job}/media/processed?download=true').headers['content-disposition'].split(';')[0], 'attachment')
        with connect(self.root) as db:
            cursor = db.execute("INSERT INTO users(username,password,role) VALUES ('otro',?,'admin')", (password_hash('test-password-other'),))
            token = secrets.token_urlsafe(32)
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (token_hash(token), cursor.lastrowid, time.time() + 60))
        original_cookie = self.client.cookies.get(COOKIE)
        self.client.cookies.clear()
        self.client.cookies.set(COOKIE, token, path='/api')
        self.assertEqual(self.client.get(f'/api/studio/jobs/{job}/media/original').status_code, 404)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(f'/api/studio/jobs/{job}/media/processed').status_code, 401)
        self.client.cookies.set(COOKIE, original_cookie, path='/api')
        self.assertEqual(self.client.delete(f'/api/studio/jobs/{job}', headers=HEADERS).status_code, 204)
        self.assertFalse((self.root / 'jobs' / job).exists())

    def test_real_ffmpeg_rejects_invalid_file_and_retry_keeps_original(self):
        self.setup_account()
        job = self.upload(b'not-a-video').json()['id']
        process(self.root, job)
        result = self.client.get('/api/studio/jobs').json()[0]
        self.assertEqual(result['status'], 'failed')
        self.assertTrue((self.root / 'jobs' / job / 'original').exists())
        self.assertFalse((self.root / 'jobs' / job / 'processed.mp4').exists())
        self.assertEqual(self.client.post(f'/api/studio/jobs/{job}/retry', headers=HEADERS).status_code, 202)
        self.assertEqual(self.client.post(f'/api/studio/jobs/{job}/retry', headers=HEADERS).status_code, 409)

    def test_upload_requires_installed_model(self):
        # Otra instancia aislada para verificar el estado sin IA instalada.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            with TestClient(create_app(path, ready_check=lambda _: False)) as client:
                (path / 'setup-token').write_text(self.token)
                client.post('/api/studio/setup', json={**self.credentials, 'token': self.token}, headers=HEADERS)
                self.assertFalse(client.get('/api/studio/status').json()['modelReady'])
                self.assertEqual(client.post('/api/studio/jobs', content=b'a', headers={**HEADERS, 'X-File-Name': 'a.mp4'}).status_code, 503)

    def test_login_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.client.post('/api/studio/login', json=self.credentials, headers=HEADERS).status_code, 401)
        self.assertEqual(self.client.post('/api/studio/login', json=self.credentials, headers=HEADERS).status_code, 429)

    def test_parse_ranges_text_and_dialogue_upload_validation(self):
        self.assertEqual(parse_ranges_text(''), [])
        self.assertEqual(parse_ranges_text('0:06-0:29'), [[6.0, 29.0]])
        self.assertEqual(parse_ranges_text('1:02.5-1:10, 6-9'), [[62.5, 70.0], [6.0, 9.0]])
        self.assertEqual(format_ranges([[5.9, 7.2]]), '0:05.9-0:07.2')
        for invalid in ('0:06', '0:29-0:06', 'abc-def', '0:06-0:29-0:30', '-5-10'):
            with self.assertRaises(ValueError):
                parse_ranges_text(invalid)
        self.setup_account()
        invalid_upload = self.client.post('/api/studio/jobs?modo=dialogo&ranges=0:06', content=b'a',
                                          headers={**HEADERS, 'X-File-Name': 'a.mp4'})
        self.assertEqual(invalid_upload.status_code, 422)
        reversed_upload = self.client.post('/api/studio/jobs?modo=dialogo&ranges=0:29-0:06', content=b'a',
                                           headers={**HEADERS, 'X-File-Name': 'a.mp4'})
        self.assertEqual(reversed_upload.status_code, 422)
        unknown_mode = self.client.post('/api/studio/jobs?modo=raro', content=b'a', headers={**HEADERS, 'X-File-Name': 'a.mp4'})
        self.assertEqual(unknown_mode.status_code, 422)
        accepted = self.client.post('/api/studio/jobs?modo=dialogo&ranges=0:01-0:02', content=b'a',
                                    headers={**HEADERS, 'X-File-Name': 'escena.mp4'})
        self.assertEqual(accepted.status_code, 202, accepted.text)
        job = accepted.json()
        self.assertEqual(job['modo'], 'dialogo')
        self.assertEqual(job['ranges'], '0:01-0:02')
        no_stems = self.client.post(f"/api/studio/jobs/{job['id']}/remix", json={'modo': 'dialogo', 'ranges': '0:00-0:01'},
                                    headers=HEADERS)
        self.assertEqual(no_stems.status_code, 409)

    def test_detect_dialogue_and_mask_gain(self):
        import numpy as np
        from .separate import detect_dialogue, gain_for
        sample_rate = 44100
        audio = np.zeros((sample_rate * 4, 2), dtype='float32')
        audio[sample_rate:2 * sample_rate] = 0.25
        ranges = detect_dialogue(audio, sample_rate)
        self.assertEqual(len(ranges), 1)
        self.assertAlmostEqual(ranges[0][0], 1.0, delta=0.2)
        self.assertAlmostEqual(ranges[0][1], 2.0, delta=0.2)
        gain = gain_for([[1.0, 2.0]], sample_rate * 4, sample_rate)
        self.assertEqual(gain[sample_rate + 2000], 0)
        self.assertEqual(gain[sample_rate // 2], 1)
        self.assertEqual(gain[sample_rate * 3], 1)
        self.assertTrue(0 < gain[sample_rate - 1000] < 1)

    def test_remix_recombines_saved_stems_without_running_model(self):
        self.setup_account()
        accepted = self.client.post('/api/studio/jobs', content=self.synthetic_video(),
                                    headers={**HEADERS, 'X-File-Name': 'escena.mp4'})
        self.assertEqual(accepted.status_code, 202, accepted.text)
        job = accepted.json()['id']
        folder = self.root / 'jobs' / job
        write_stereo(folder / 'stems' / 'vocals.wav')
        write_stereo(folder / 'stems' / 'background.wav')
        with connect(self.root) as db:
            db.execute("UPDATE jobs SET status='ready',progress=100,message='ok',seconds=1 WHERE id=?", (job,))
        outside = self.client.post(f'/api/studio/jobs/{job}/remix', json={'modo': 'dialogo', 'ranges': '0:02-0:03'},
                                   headers=HEADERS)
        self.assertEqual(outside.status_code, 422)
        remix(self.root, job, 'dialogo', '0:00-0:01')
        row = self.client.get('/api/studio/jobs').json()[0]
        self.assertEqual(row['status'], 'ready')
        self.assertEqual(row['modo'], 'dialogo')
        self.assertEqual(row['ranges'], '0:00-0:01')
        self.assertTrue((folder / 'processed.mp4').is_file())
        self.assertGreater((folder / 'processed.mp4').stat().st_size, 1000)
        self.assertFalse((folder / 'mixed.wav').exists())
        self.assertTrue((folder / 'stems' / 'vocals.wav').is_file())
        queued = self.client.post(f'/api/studio/jobs/{job}/remix', json={'modo': 'voces', 'ranges': ''}, headers=HEADERS)
        self.assertEqual(queued.status_code, 202, queued.text)
        with connect(self.root) as db:
            current = db.execute('SELECT status,modo,ranges FROM jobs WHERE id=?', (job,)).fetchone()
        self.assertEqual(current['status'], 'queued')
        self.assertEqual(current['modo'], 'voces')
        self.assertEqual(current['ranges'], '')

    def test_voz_upload_requires_speaker_models(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            with TestClient(create_app(path, ready_check=lambda _: True, speaker_ready_check=lambda _: False)) as client:
                (path / 'setup-token').write_text(self.token)
                client.post('/api/studio/setup', json={**self.credentials, 'token': self.token}, headers=HEADERS)
                self.assertFalse(client.get('/api/studio/status').json()['speakerReady'])
                blocked = client.post('/api/studio/jobs?modo=voz', content=b'a', headers={**HEADERS, 'X-File-Name': 'a.mp4'})
                self.assertEqual(blocked.status_code, 503)
                self.assertEqual(client.post('/api/studio/jobs', content=b'a', headers={**HEADERS, 'X-File-Name': 'a.mp4'}).status_code, 202)

    def test_voz_mode_endpoints_speakers_samples_and_remove_voice(self):
        self.setup_account()
        accepted = self.upload(b'escena-de-voces', modo='voz')
        self.assertEqual(accepted.status_code, 202, accepted.text)
        self.assertEqual(accepted.json()['modo'], 'voz')
        job = accepted.json()['id']
        folder = self.root / 'jobs' / job
        # Sin voces separadas todavía no se puede escuchar ni quitar nada.
        self.assertEqual(self.client.get(f'/api/studio/jobs/{job}/speakers').status_code, 409)
        self.assertEqual(self.client.get(f'/api/studio/jobs/{job}/media/sample?which=1').status_code, 404)
        self.assertEqual(self.client.post(f'/api/studio/jobs/{job}/remove-voice', json={'target': '1'}, headers=HEADERS).status_code, 409)
        self.assertEqual(self.client.post(f'/api/studio/jobs/{job}/remove-voice', json={'target': '9'}, headers=HEADERS).status_code, 422)
        stems = folder / 'stems'
        write_stereo(stems / 'vocals.wav')
        write_stereo(stems / 'background.wav')
        write_stereo(stems / 'speaker-1.wav', seconds=0.5)
        write_stereo(stems / 'speaker-2.wav', seconds=0.5)
        write_stereo(stems / 'sample-1.wav', seconds=0.5)
        write_stereo(stems / 'sample-2.wav', seconds=0.5)
        (stems / 'speakers.json').write_text('{"voices": [], "n_voices": 0}', encoding='utf-8')
        with connect(self.root) as db:
            db.execute("UPDATE jobs SET status='voices',progress=100 WHERE id=?", (job,))
        info = self.client.get(f'/api/studio/jobs/{job}/speakers')
        self.assertEqual(info.status_code, 200)
        self.assertEqual(info.json()['n_voices'], 0)
        sample = self.client.get(f'/api/studio/jobs/{job}/media/sample?which=1')
        self.assertEqual(sample.status_code, 200)
        self.assertEqual(sample.headers['content-type'], 'audio/wav')
        self.assertEqual(self.client.get(f'/api/studio/jobs/{job}/media/sample?which=3').status_code, 404)
        queued = self.client.post(f'/api/studio/jobs/{job}/remove-voice', json={'target': '1'}, headers=HEADERS)
        self.assertEqual(queued.status_code, 202, queued.text)
        with connect(self.root) as db:
            row = db.execute('SELECT status FROM jobs WHERE id=?', (job,)).fetchone()
        self.assertEqual(row['status'], 'queued')
        deadline = time.time() + 2
        while not self.removed and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.removed[0][1:], (job, 1))
        # Un trabajo en modo diálogo no acepta quitar voz.
        other = self.upload(b'otra', modo='dialogo').json()['id']
        with connect(self.root) as db:
            db.execute("UPDATE jobs SET status='ready' WHERE id=?", (other,))
        self.assertEqual(self.client.post(f'/api/studio/jobs/{other}/remove-voice', json={'target': '1'}, headers=HEADERS).status_code, 409)
        self.assertEqual(self.client.get(f'/api/studio/jobs/{other}/speakers').status_code, 409)

    def test_process_voz_reaches_voices_state_without_ai(self):
        from unittest import mock
        from . import processing as processing_module
        self.setup_account()
        job = self.upload(self.synthetic_video(seconds=1), modo='voz').json()['id']
        folder = self.root / 'jobs' / job

        def fake_execute(args, log, timeout):
            if 'backend.speakers' in args:
                stems = folder / 'stems'
                (stems / 'speakers.json').write_text('{"voices": []}', encoding='utf-8')
                for name in ('speaker-1.wav', 'speaker-2.wav', 'sample-1.wav', 'sample-2.wav'):
                    write_stereo(stems / name, seconds=0.3)
            elif 'backend.separate' in args:
                write_stereo(folder / 'stems' / 'vocals.wav', seconds=1)
                write_stereo(folder / 'stems' / 'background.wav', seconds=1)
            else:
                write_stereo(folder / 'audio.wav', seconds=1)

        with mock.patch.object(processing_module, 'execute', side_effect=fake_execute):
            process(self.root, job)
        row = self.client.get('/api/studio/jobs').json()[0]
        self.assertEqual(row['status'], 'voices')
        self.assertEqual(row['modo'], 'voz')
        self.assertEqual(row['progress'], 100)
        self.assertIn('Escuchá cada voz', row['message'])
        self.assertFalse((folder / 'processed.mp4').exists())
        self.assertFalse((folder / 'audio.wav').exists())
        self.assertTrue((folder / 'stems' / 'speakers.json').is_file())

    def test_single_speaker_fast_path_skips_sepformer_and_can_remove_voice(self):
        from unittest import mock
        import soundfile as sf
        from .speakers import run_remove, run_separate

        stems = self.root / 'stems-single'
        write_stereo(stems / 'vocals.wav', seconds=1)
        write_stereo(stems / 'background.wav', seconds=1)
        diarization = {'segments': [[0.0, 1.0]], 'windows': [[0.0, 1.0]],
                       'labels': [0], 'n_clusters': 1}
        with mock.patch('backend.speakers.diarize', return_value=diarization), \
             mock.patch('backend.speakers._separate_streams', side_effect=AssertionError('SepFormer no debe ejecutarse')):
            run_separate(stems, self.root)
        summary = (stems / 'speakers.json').read_text(encoding='utf-8')
        self.assertIn('single-speaker-fast-path', summary)
        self.assertEqual(len(list(stems.glob('speaker-*.wav'))), 1)
        self.assertEqual(len(list(stems.glob('sample-*.wav'))), 1)
        output = stems / 'single-removed.wav'
        run_remove(stems, 1, 'suma', output)
        mixed, _ = sf.read(output, dtype='float32', always_2d=True)
        background, _ = sf.read(stems / 'background.wav', dtype='float32', always_2d=True)
        self.assertTrue(mixed.shape == background.shape)
        self.assertTrue((abs(mixed - background) < 1e-3).all())

    def test_orchestrator_profiles_media_and_selects_models_by_mode(self):
        from .orchestrator import build_plan, probe_media
        from .processing import INPUT_OPTIONS, ffmpeg

        with tempfile.TemporaryDirectory() as sample:
            path = Path(sample) / 'profile.mp4'
            path.write_bytes(self.synthetic_video(seconds=1))
            profile = probe_media(ffmpeg(), path, INPUT_OPTIONS)
        self.assertTrue(profile.has_video)
        self.assertTrue(profile.has_audio)
        self.assertEqual(profile.video_codec, 'h264')
        self.assertEqual(profile.audio_codec, 'aac')
        self.assertEqual(build_plan('dialogo', profile).stages, ('demucs', 'dialogue-mask'))
        speaker_plan = build_plan('voz', profile)
        self.assertEqual(speaker_plan.demucs_model, 'htdemucs')
        self.assertEqual(speaker_plan.speaker_model, 'auto: ECAPA/VAD → SepFormer 2 o 3 voces')
        self.assertEqual(build_plan('voces', profile).stages, ('demucs', 'remove-vocals'))

    def test_run_remove_strategies_and_helpers(self):
        import importlib.util
        import numpy as np
        import soundfile as sf
        from .speakers import _pitch, _runs, run_remove
        stems = self.root / 'stems-voces'
        write_stereo(stems / 'vocals.wav', seconds=1)
        write_stereo(stems / 'background.wav', seconds=1)
        write_stereo(stems / 'speaker-1.wav', seconds=1)
        write_stereo(stems / 'speaker-2.wav', seconds=1)
        vocals, _ = sf.read(stems / 'vocals.wav', dtype='float32', always_2d=True)
        background, _ = sf.read(stems / 'background.wav', dtype='float32', always_2d=True)
        speaker1, _ = sf.read(stems / 'speaker-1.wav', dtype='float32', always_2d=True)
        speaker2, _ = sf.read(stems / 'speaker-2.wav', dtype='float32', always_2d=True)
        suma_path, resta_path = stems / 'suma.wav', stems / 'resta.wav'
        run_remove(stems, 1, 'suma', suma_path)
        run_remove(stems, 1, 'resta', resta_path)
        suma, _ = sf.read(suma_path, dtype='float32', always_2d=True)
        resta, _ = sf.read(resta_path, dtype='float32', always_2d=True)
        self.assertTrue(np.allclose(suma, background + speaker2, atol=1e-3))
        self.assertTrue(np.allclose(resta, vocals + background - speaker1, atol=1e-3))
        self.assertTrue(np.isfinite(suma).all() and np.isfinite(resta).all())
        self.assertLessEqual(float(np.abs(suma).max()), 0.991)
        with self.assertRaises(ValueError):
            run_remove(stems, 9, 'suma', stems / 'otro.wav')
        # Ayudantes de análisis de voz.
        self.assertEqual(_runs([1, 2, 3, 7, 8, 20]), [[1, 2, 3], [7, 8], [20]])
        import numpy as np2
        sample_rate = 16000
        sine = np2.sin(2 * np2.pi * 180 * np2.arange(sample_rate) / sample_rate).astype('float32') * 0.3
        strength, hz = _pitch(sine[:sample_rate // 2], sample_rate)
        self.assertGreater(strength, 0.5)
        self.assertAlmostEqual(hz, 180, delta=15)
        rng = np2.random.default_rng(0)
        noise_strength, _ = _pitch(rng.standard_normal(sample_rate // 2).astype('float32') * 1e-4, sample_rate)
        self.assertLess(noise_strength, 0.2)
        if not all(importlib.util.find_spec(module) for module in ('speechbrain', 'silero_vad', 'sklearn')):
            self.skipTest('dependencias de IA no instaladas')
        from .speakers import speaker_ready
        self.assertFalse(speaker_ready(self.root))
        (self.root / 'speaker-model-ready.json').write_text('{"models": ["sepformer-whamr16k"]}', encoding='utf-8')
        self.assertFalse(speaker_ready(self.root))
        base = self.root / 'models' / 'speakers' / 'sepformer-whamr16k'
        base.mkdir(parents=True)
        (base / 'hyperparams.yaml').write_text('sample_rate: 16000', encoding='utf-8')
        self.assertTrue(speaker_ready(self.root))

    def test_initialize_migrates_jobs_table_for_voz_mode(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            con = sqlite3.connect(path / 'studio.sqlite3')
            con.executescript('''
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin', 'subscriber')));
            INSERT INTO users VALUES (1, 'equipo', 'x', 'admin');
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                name TEXT NOT NULL, modo TEXT NOT NULL DEFAULT 'voces' CHECK(modo IN ('voces', 'dialogo')),
                ranges TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '', created REAL NOT NULL, seconds REAL);
            INSERT INTO jobs VALUES ('viejo', 1, 'video.mp4', 'dialogo', '', 'ready', 100, '', 1, NULL);
            ''')
            con.commit()
            con.close()
            initialize(path)
            con = sqlite3.connect(path / 'studio.sqlite3')
            rows = con.execute('SELECT id, modo FROM jobs').fetchall()
            con.execute("INSERT INTO jobs VALUES ('nuevo', 1, 'b.mp4', 'voz', '', 'voices', 100, '', 2, NULL)")
            con.commit()
            con.close()
            self.assertEqual(rows, [('viejo', 'dialogo')])


if __name__ == '__main__':
    unittest.main()
