"""Servidor exclusivamente de pruebas, con datos temporales y un video sintético."""
import shutil
import subprocess
import tempfile
from pathlib import Path

import uvicorn
from fastapi.responses import FileResponse

from .app import create_app
from .config import data_directory
from .processing import ffmpeg, model_ready
from .speakers import speaker_ready


if __name__ == '__main__':
    installed = data_directory()
    if not model_ready(installed):
        raise SystemExit('Instalá el modelo antes de ejecutar test:studio.')
    if not speaker_ready(installed):
        raise SystemExit('Instalá los modelos de voces: python -m backend.manage install-speaker-models')
    with tempfile.TemporaryDirectory(prefix='doblaje-browser-') as temporary:
        root = Path(temporary)
        shutil.copytree(installed / 'models', root / 'models')
        shutil.copyfile(installed / 'model-ready.json', root / 'model-ready.json')
        shutil.copyfile(installed / 'speaker-model-ready.json', root / 'speaker-model-ready.json')
        # Clave solo de este servidor efímero, nunca aceptada por backend.run.
        (root / 'setup-token').write_text('studio-browser-setup-test-only')
        fixture = root / 'synthetic.mp4'
        subprocess.run([ffmpeg(), '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=24',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '2', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(fixture)], check=True, timeout=60)
        app = create_app(root)

        @app.get('/api/studio/test-fixture')
        def sample():
            return FileResponse(fixture, media_type='video/mp4')

        uvicorn.run(app, host='127.0.0.1', port=8766)
