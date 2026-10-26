"""Prueba real de FFmpeg + Demucs, con video sintético. No mide calidad de diálogos."""
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from .app import create_app
from .config import data_directory
from .processing import ffmpeg, model_ready


def main():
    configured_root = data_directory()
    if not model_ready(configured_root):
        raise SystemExit('Primero ejecutá python -m backend.manage install-model')
    with tempfile.TemporaryDirectory(prefix='doblaje-smoke-') as temporary:
        root = Path(temporary)
        # Compartir por copia los pesos, sin alterar cuentas ni videos existentes.
        shutil.copytree(configured_root / 'models', root / 'models')
        shutil.copyfile(configured_root / 'model-ready.json', root / 'model-ready.json')
        sample = root / 'synthetic.mp4'
        subprocess.run([ffmpeg(), '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=24',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '2', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(sample)], check=True, timeout=60)
        with TestClient(create_app(root)) as client:
            token = secrets.token_urlsafe(32)
            (root / 'setup-token').write_text(token)
            headers = {'X-Doblaje-Request': 'studio'}
            result = client.post('/api/studio/setup', json={'username': 'smoke', 'password': secrets.token_urlsafe(24), 'token': token}, headers=headers)
            assert result.status_code == 201, result.text
            result = client.post('/api/studio/jobs', content=sample.read_bytes(), headers={**headers, 'X-File-Name': 'synthetic.mp4'})
            assert result.status_code == 202, result.text
            job_id = result.json()['id']
            deadline = time.time() + 600
            while time.time() < deadline:
                job = client.get('/api/studio/jobs').json()[0]
                if job['status'] in ('failed', 'ready'):
                    break
                time.sleep(1)
            if job['status'] != 'ready':
                print((root / 'jobs' / job_id / 'processing.log').read_text(errors='replace'))
                raise RuntimeError(job['message'])
            output = root / 'jobs' / job_id / 'processed.mp4'
            assert output.stat().st_size > 1000
            subprocess.run([ffmpeg(), '-nostdin', '-v', 'error', '-i', str(output), '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'], check=True, timeout=60)
            response = client.get(f'/api/studio/jobs/{job_id}/media/processed?download=true')
            assert response.status_code == 200 and response.content == output.read_bytes()
            print(f'OK: carga autenticada -> FFmpeg -> Demucs real -> MP4 H.264/AAC -> descarga ({len(response.content)} bytes).')
            print('Entrada sintetica de 2 segundos: no verifica eliminacion de dialogos ni calidad auditiva.')


if __name__ == '__main__':
    main()
