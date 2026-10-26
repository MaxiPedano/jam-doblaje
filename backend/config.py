import os
from pathlib import Path


def data_directory() -> Path:
    configured = os.environ.get('DOBLAJE_DATA_DIR')
    if configured:
        return Path(configured).expanduser().resolve()
    root = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local' / 'share')))
    return root / 'DoblajeStudio'


MAX_UPLOAD = 500 * 1024 * 1024
MAX_SECONDS = 600
SESSION_SECONDS = 8 * 60 * 60
MODEL = 'htdemucs'
