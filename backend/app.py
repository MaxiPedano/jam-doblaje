import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import hmac
import json
from pathlib import Path
import secrets
import shutil
import threading
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import check_password, password_hash, token_hash
from .config import MAX_SECONDS, MAX_UPLOAD, SESSION_SECONDS, data_directory
from .db import connect, initialize
from .processing import in_duration, model_ready, parse_ranges_text, process, remix as remix_job, stem_duration
from .speakers import remove_voice, speaker_ready

COOKIE = 'doblaje_session'
ORIGINS = {f'http://{host}:{port}' for host in ('localhost', '127.0.0.1') for port in (5173, 5178, 5179, 4173, 8765)}


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r'^[a-zA-Z0-9_.-]+$')
    password: str = Field(min_length=12, max_length=128)


class Setup(Credentials):
    token: str = Field(min_length=20, max_length=128)


class Remix(BaseModel):
    modo: str = 'dialogo'
    ranges: str = Field(default='', max_length=400)


class RemoveVoice(BaseModel):
    target: str = Field(pattern=r'^[12]$')


def create_app(root: Path | None = None, runner=process, ready_check=model_ready,
               remix_runner=remix_job, speaker_ready_check=speaker_ready, remove_runner=remove_voice):
    root = root or data_directory()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='separation')
    queue_lock = threading.Lock()
    attempts: dict[str, list[float]] = {}

    @asynccontextmanager
    async def lifespan(app):
        initialize(root)
        with connect(root) as db:
            db.execute("UPDATE jobs SET status='failed',progress=0,message='El servidor se reinició. Podés reintentar el trabajo.' WHERE status IN ('uploading','queued','processing')")
        yield
        executor.shutdown(wait=True)

    app = FastAPI(title='Doblaje Studio local', lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])

    @app.middleware('http')
    async def browser_protection(request: Request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('x-doblaje-request') != 'studio':
                return JSONResponse({'detail': 'Solicitud no autorizada.'}, status_code=403)
            origin = request.headers.get('origin')
            if origin and origin not in ORIGINS:
                return JSONResponse({'detail': 'Origen no permitido.'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def current_user(request: Request):
        token = request.cookies.get(COOKIE, '')
        with connect(root) as db:
            row = db.execute('SELECT users.id,username,role FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?', (token_hash(token), time.time())).fetchone()
        if not row:
            raise HTTPException(401, 'Iniciá sesión con la cuenta del equipo.')
        return dict(row)

    def admin(user=Depends(current_user)):
        if user['role'] != 'admin':
            raise HTTPException(403, 'Solo el equipo puede cargar y procesar videos.')
        return user

    def session(response: Response, user_id: int):
        token = secrets.token_urlsafe(48)
        with connect(root) as db:
            db.execute('DELETE FROM sessions WHERE expires<=?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (token_hash(token), user_id, time.time() + SESSION_SECONDS))
        # Servicio estrictamente local HTTP. En producción HTTPS se requiere Secure.
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', max_age=SESSION_SECONDS, path='/api')

    def rate_limit(request: Request):
        key = request.client.host if request.client else 'local'
        recent = [t for t in attempts.get(key, []) if t > time.time() - 300]
        if len(recent) >= 10:
            raise HTTPException(429, 'Demasiados intentos. Esperá cinco minutos.')
        attempts[key] = [*recent, time.time()]

    @app.get('/api/studio/status')
    def status():
        with connect(root) as db:
            configured = bool(db.execute('SELECT 1 FROM users LIMIT 1').fetchone())
        return {'configured': configured, 'modelReady': ready_check(root), 'speakerReady': speaker_ready_check(root),
                'maxUploadBytes': MAX_UPLOAD, 'maxSeconds': MAX_SECONDS, 'mode': 'local', 'model': 'htdemucs'}

    @app.post('/api/studio/setup', status_code=201)
    def setup(payload: Setup, request: Request, response: Response):
        rate_limit(request)
        with queue_lock, connect(root) as db:
            if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                raise HTTPException(409, 'La cuenta del equipo ya está configurada.')
            file = root / 'setup-token'
            if not file.exists() or not hmac.compare_digest(file.read_text(encoding='utf-8').strip(), payload.token):
                raise HTTPException(403, 'Clave de instalación incorrecta. Obtenela con el comando setup-token.')
            cursor = db.execute("INSERT INTO users(username,password,role) VALUES (?,?,'admin')", (payload.username.lower(), password_hash(payload.password)))
            user_id = cursor.lastrowid
        file.unlink(missing_ok=True)
        session(response, user_id)
        return {'id': user_id, 'username': payload.username.lower(), 'role': 'admin'}

    @app.post('/api/studio/login')
    def login(payload: Credentials, request: Request, response: Response):
        rate_limit(request)
        with connect(root) as db:
            user = db.execute('SELECT * FROM users WHERE username=?', (payload.username.lower(),)).fetchone()
        # Mismo trabajo de hash para usuarios inexistentes.
        stored = user['password'] if user else '00' * 16 + ':' + '00' * 64
        if not check_password(payload.password, stored) or not user:
            raise HTTPException(401, 'Usuario o contraseña incorrectos.')
        session(response, user['id'])
        return {'id': user['id'], 'username': user['username'], 'role': user['role']}

    @app.get('/api/studio/me')
    def me(user=Depends(current_user)):
        return user

    @app.post('/api/studio/logout', status_code=204)
    def logout(request: Request, response: Response):
        with connect(root) as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(request.cookies.get(COOKIE, '')),))
        response.delete_cookie(COOKIE, path='/api')

    def owned_job(job_id: str, user: dict):
        with connect(root) as db:
            row = db.execute('SELECT * FROM jobs WHERE id=? AND user_id=?', (job_id, user['id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Trabajo no encontrado.')
        return dict(row)

    def check_capacity(db):
        if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('uploading','queued','processing')").fetchone()[0] >= 3:
            raise HTTPException(409, 'Ya hay tres trabajos en curso. Esperá que termine uno.')
        if shutil.disk_usage(root).free < 2 * 1024**3:
            raise HTTPException(507, 'Se necesitan al menos 2 GB libres para procesar.')

    @app.get('/api/studio/jobs')
    def jobs(user=Depends(admin)):
        with connect(root) as db:
            return [dict(row) for row in db.execute('SELECT * FROM jobs WHERE user_id=? ORDER BY created DESC', (user['id'],))]

    @app.post('/api/studio/jobs', status_code=202)
    async def upload(request: Request, user=Depends(admin)):
        if not ready_check(root):
            raise HTTPException(503, 'Instalá las dependencias de IA y el modelo antes de cargar videos.')
        from urllib.parse import unquote
        name = unquote(request.headers.get('x-file-name', 'video.mp4'))
        name = name.replace('\\', '/').split('/')[-1][:180]
        if Path(name).suffix.lower() not in ('.mp4', '.mov', '.mkv', '.webm', '.m4v', '.avi'):
            raise HTTPException(415, 'Formato no admitido. Usá MP4, MOV, MKV, WebM, M4V o AVI.')
        length = request.headers.get('content-length')
        if length and (not length.isdigit() or int(length) > MAX_UPLOAD):
            raise HTTPException(413, 'El archivo supera los 500 MB.')
        modo = request.query_params.get('modo', 'voces')
        if modo not in ('voces', 'dialogo', 'voz'):
            raise HTTPException(422, 'Modo no admitido. Usá quitar todas las voces, solo el diálogo marcado o una voz por hablante.')
        if modo == 'voz' and not speaker_ready_check(root):
            raise HTTPException(503, 'Instalá los modelos de voces con “python -m backend.manage install-speaker-models” antes de cargar videos.')
        ranges_text = request.query_params.get('ranges', '').strip()[:400] if modo == 'dialogo' else ''
        if ranges_text:
            try:
                parse_ranges_text(ranges_text)
            except ValueError as error:
                raise HTTPException(422, str(error))
        job_id = str(uuid.uuid4())
        folder = root / 'jobs' / job_id
        with queue_lock, connect(root) as db:
            check_capacity(db)
            db.execute("INSERT INTO jobs(id,user_id,name,modo,ranges,status,created,message) VALUES (?,?,?,?,?,'uploading',?,'Recibiendo archivo…')",
                       (job_id, user['id'], name, modo, ranges_text, time.time()))
        try:
            folder.mkdir()
            size = 0
            with (folder / 'original').open('wb') as file:
                async with asyncio.timeout(600):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > MAX_UPLOAD:
                            raise HTTPException(413, 'El archivo supera los 500 MB.')
                        file.write(chunk)
            if size == 0:
                raise HTTPException(400, 'El archivo está vacío.')
            with connect(root) as db:
                db.execute("UPDATE jobs SET status='queued',message='Esperando turno…' WHERE id=?", (job_id,))
            executor.submit(runner, root, job_id)
            return owned_job(job_id, user)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            with connect(root) as db:
                db.execute('DELETE FROM jobs WHERE id=?', (job_id,))
            raise

    @app.post('/api/studio/jobs/{job_id}/retry', status_code=202)
    def retry(job_id: str, user=Depends(admin)):
        job = owned_job(job_id, user)
        if job['status'] != 'failed':
            raise HTTPException(409, 'Solo se pueden reintentar trabajos fallidos.')
        if not ready_check(root):
            raise HTTPException(503, 'El modelo no está instalado.')
        if not (root / 'jobs' / job_id / 'original').is_file():
            raise HTTPException(409, 'El original no está disponible. Eliminá el trabajo y volvé a cargarlo.')
        with queue_lock, connect(root) as db:
            check_capacity(db)
            cursor = db.execute("UPDATE jobs SET status='queued',progress=0,message='Esperando turno…' WHERE id=? AND status='failed'", (job_id,))
            if not cursor.rowcount:
                raise HTTPException(409, 'El trabajo ya está en curso.')
        executor.submit(runner, root, job_id)
        return {'accepted': True}

    @app.post('/api/studio/jobs/{job_id}/remix', status_code=202)
    def remix(job_id: str, payload: Remix, user=Depends(admin)):
        job = owned_job(job_id, user)
        if job['status'] not in ('ready', 'failed'):
            raise HTTPException(409, 'Esperá a que termine el procesamiento antes de ajustar los tramos.')
        if payload.modo not in ('voces', 'dialogo'):
            raise HTTPException(422, 'Modo no admitido. Usá quitar todas las voces o solo el diálogo marcado.')
        modo = payload.modo
        ranges_text = payload.ranges.strip()[:400] if modo == 'dialogo' else ''
        folder = root / 'jobs' / job_id
        if not (folder / 'stems' / 'vocals.wav').is_file() or not (folder / 'stems' / 'background.wav').is_file():
            raise HTTPException(409, 'Este trabajo no tiene pistas separadas. Eliminálo y volvé a cargar el video.')
        if ranges_text:
            try:
                duration = stem_duration(folder / 'stems')
                if not in_duration(parse_ranges_text(ranges_text), duration):
                    raise HTTPException(422, 'Los tramos marcados quedan fuera de la duración del video.')
            except HTTPException:
                raise
            except (OSError, ValueError) as error:
                raise HTTPException(409, f'Las pistas guardadas no están disponibles: {error}')
        with queue_lock, connect(root) as db:
            check_capacity(db)
            cursor = db.execute("UPDATE jobs SET status='queued',progress=0,message='En cola para ajustar tramos…',modo=?,ranges=? WHERE id=? AND status IN ('ready','failed')",
                                (modo, ranges_text, job_id))
            if not cursor.rowcount:
                raise HTTPException(409, 'El trabajo ya está en curso.')
        executor.submit(remix_runner, root, job_id, modo, ranges_text)
        return {'accepted': True}

    @app.post('/api/studio/jobs/{job_id}/remove-voice', status_code=202)
    def remove_voice_endpoint(job_id: str, payload: RemoveVoice, user=Depends(admin)):
        job = owned_job(job_id, user)
        if job['modo'] != 'voz':
            raise HTTPException(409, 'Este trabajo no está en modo de voz por hablante.')
        if job['status'] not in ('voices', 'ready'):
            raise HTTPException(409, 'Esperá a que termine la separación de voces.')
        folder = root / 'jobs' / job_id
        for name in ('vocals.wav', 'background.wav', 'speaker-1.wav', 'speaker-2.wav', 'speakers.json'):
            if not (folder / 'stems' / name).is_file():
                raise HTTPException(409, 'Este trabajo no tiene voces separadas. Eliminálo y volvé a cargar el video.')
        if not (folder / 'original').is_file():
            raise HTTPException(409, 'El original no está disponible. Eliminá el trabajo y volvé a cargarlo.')
        target = int(payload.target)
        with queue_lock, connect(root) as db:
            check_capacity(db)
            cursor = db.execute("UPDATE jobs SET status='queued',progress=0,message='En cola para quitar la voz…' WHERE id=? AND status IN ('voices','ready')",
                                (job_id,))
            if not cursor.rowcount:
                raise HTTPException(409, 'El trabajo ya está en curso.')
        executor.submit(remove_runner, root, job_id, target)
        return {'accepted': True}

    @app.get('/api/studio/jobs/{job_id}/speakers')
    def speakers(job_id: str, user=Depends(admin)):
        job = owned_job(job_id, user)
        if job['modo'] != 'voz':
            raise HTTPException(409, 'Este trabajo no está en modo de voz por hablante.')
        file = root / 'jobs' / job_id / 'stems' / 'speakers.json'
        if not file.is_file():
            raise HTTPException(409, 'Todavía no hay voces separadas en este trabajo.')
        try:
            return json.loads(file.read_text(encoding='utf-8'))
        except ValueError:
            raise HTTPException(500, 'Las voces separadas están dañadas. Eliminá el trabajo y volvé a cargarlo.')

    @app.delete('/api/studio/jobs/{job_id}', status_code=204)
    def delete(job_id: str, user=Depends(admin)):
        with queue_lock:
            job = owned_job(job_id, user)
            if job['status'] not in ('ready', 'failed'):
                raise HTTPException(409, 'Esperá a que termine el procesamiento antes de eliminar.')
            folder = root / 'jobs' / job_id
            if folder.exists():
                shutil.rmtree(folder)
            with connect(root) as db:
                db.execute('DELETE FROM jobs WHERE id=?', (job_id,))

    @app.get('/api/studio/jobs/{job_id}/media/{variant}')
    def media(job_id: str, variant: str, download: bool = False, which: int = 1, user=Depends(admin)):
        job = owned_job(job_id, user)
        if variant not in ('original', 'processed', 'sample'):
            raise HTTPException(404, 'Archivo no encontrado.')
        if variant == 'processed' and job['status'] != 'ready':
            raise HTTPException(409, 'El video procesado todavía no está disponible.')
        if variant == 'sample':
            if which not in (1, 2):
                raise HTTPException(404, 'Archivo no encontrado.')
            path = root / 'jobs' / job_id / 'stems' / f'sample-{which}.wav'
            if not path.is_file():
                raise HTTPException(404, 'Archivo no encontrado.')
            return FileResponse(path, media_type='audio/wav', filename=f'doblaje-{job_id}-voz-{which}.wav',
                                content_disposition_type='attachment' if download else 'inline')
        path = root / 'jobs' / job_id / ('original' if variant == 'original' else 'processed.mp4')
        if not path.is_file():
            raise HTTPException(404, 'Archivo no encontrado.')
        extension = Path(job['name']).suffix.lower()
        mime = 'video/mp4' if variant == 'processed' else {'.webm': 'video/webm', '.mov': 'video/quicktime', '.mkv': 'video/x-matroska', '.avi': 'video/x-msvideo'}.get(extension, 'video/mp4')
        filename = f'doblaje-{job_id}-sin-voces.mp4' if variant == 'processed' else job['name']
        return FileResponse(path, media_type=mime, filename=filename, content_disposition_type='attachment' if download else 'inline')

    return app


app = create_app()
