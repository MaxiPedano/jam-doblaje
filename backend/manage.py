import argparse
import getpass
import json
import os
import secrets

from .auth import password_hash
from .config import MODEL, data_directory
from .db import connect, initialize


def main():
    parser = argparse.ArgumentParser(description='Preparación local de Doblaje Studio')
    parser.add_argument('command', choices=['setup-token', 'install-model', 'install-speaker-models', 'reset-password', 'path'])
    command = parser.parse_args().command
    root = data_directory()
    initialize(root)
    if command == 'path':
        print(root)
    elif command == 'install-speaker-models':
        from .speakers import install_models, speaker_ready
        print('Descargando modelos de voces (SepFormer 2 y 3 voces, ECAPA). Los archivos quedan fuera del repositorio.')
        try:
            install_models(root)
        except ImportError:
            print('Faltan dependencias de IA. Instalalas con: pip install -r backend/requirements-ai.txt')
            return
        except Exception as error:
            print(f'No se pudieron descargar los modelos: {error}')
            print('Verificá la conexión y volvé a ejecutar el comando.')
            return
        if speaker_ready(root):
            print('Modelos de voces listos. Reiniciá el backend para que Studio los use.')
        else:
            print('La descarga quedó incompleta. Volvé a ejecutar el comando.')
    elif command == 'reset-password':
        username = input('Usuario a restablecer: ').strip().lower()
        if not username:
            print('El usuario no puede estar vacío.')
            return
        password = getpass.getpass('Nueva contraseña (mínimo 12 caracteres): ')
        confirmation = getpass.getpass('Repetí la nueva contraseña: ')
        if len(password) < 12:
            print('La contraseña debe tener al menos 12 caracteres.')
            return
        if password != confirmation:
            print('Las contraseñas no coinciden.')
            return
        with connect(root) as db:
            user = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
            if not user:
                print(f'No existe la cuenta {username}.')
                return
            db.execute('UPDATE users SET password=? WHERE id=?', (password_hash(password), user['id']))
            db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
        print(f'Contraseña actualizada para {username}. Las sesiones anteriores fueron cerradas.')
    elif command == 'setup-token':
        with connect(root) as db:
            if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                print('El equipo ya tiene una cuenta. Iniciá sesión desde Studio.')
                return
        file = root / 'setup-token'
        if not file.exists():
            file.write_text(secrets.token_urlsafe(32), encoding='utf-8')
        print('Clave de instalación local (no compartir ni subir al repositorio):')
        print(file.read_text(encoding='utf-8'))
    else:
        os.environ['TORCH_HOME'] = str(root / 'models')
        from demucs.pretrained import get_model
        print('Descargando/verificando el modelo htdemucs. Los archivos quedan fuera del repositorio.')
        model = get_model(MODEL)
        model.eval()
        (root / 'model-ready.json').write_text(json.dumps({'model': MODEL}), encoding='utf-8')
        print('Modelo listo. Iniciá el backend y abrí Studio.')


if __name__ == '__main__':
    main()
