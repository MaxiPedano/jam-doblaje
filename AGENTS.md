# Instrucciones para agentes

## Arquitectura

- `src/` es Vue 3 + TypeScript + Vite; `src/main.ts` inicia la app y las rutas usan hash routing. El catálogo y suscripciones son estado local/demo.
- `backend/` es FastAPI + SQLite + FFmpeg + IA local. `python -m backend.run` inicia el backend real en `127.0.0.1:8765`; debe tener un solo worker porque la cola no es distribuida.
- `backend/orchestrator.py` perfila medios y construye planes; `processing.py` ejecuta el plan; `separate.py` y `speakers.py` implementan separación y hablantes.
- Vite sirve normalmente en `5173` y reenvía `/api` a `8765`; `STUDIO_API_TARGET` permite cambiar ese destino. Studio está en `/#/studio`.

## Preparación Y Comandos

```powershell
npm ci
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-ai.txt
.\.venv\Scripts\python.exe -m backend.manage install-model
# Solo para el modo “Una sola voz” y test:studio:
.\.venv\Scripts\python.exe -m backend.manage install-speaker-models
```

- Verificación normal: `npm run typecheck`, `npm test`, `npm run build`; `npm run preview` sirve `dist` en `4173`.
- Tests frontend enfocados: `npm exec vitest run src/domain.test.ts`; backend: `.\.venv\Scripts\python.exe -m unittest backend.test_backend -v`.
- `npm run test:e2e` inicia Vite en `5178` y ejecuta `e2e/`; requiere Chromium (`npx playwright install chromium --no-shell`).
- `npm run test:studio` inicia `backend.browser_server` en `8766` y Vite en `5179`, con SQLite/video temporales y modelos copiados; es lento, usa IA real y requiere ambos modelos instalados.
- El servidor de Studio real no se sustituye por `backend.browser_server`; reiniciar `backend.run` tras cambios de backend si el proceso ya estaba iniciado.

## Datos Y Restricciones

- Datos, SQLite, originales, resultados y modelos viven fuera del repo en `%LOCALAPPDATA%\DoblajeStudio`; `DOBLAJE_DATA_DIR` cambia esa raíz.
- El modelo principal es Demucs `htdemucs`, local y en CPU. El modo de hablantes agrega Silero VAD, ECAPA y SepFormer; si detecta un único hablante, evita SepFormer usando la pista vocal de Demucs.
- No guardar en el repo videos, audios, modelos, bases SQLite, tokens, credenciales, secretos ni logs privados.
- Para audio, conservar la selección estructurada de planes, los argumentos de subprocess como listas y la cola de un solo worker; no concatenar comandos shell ni paralelizar IA sin medir recursos.
- Antes de cambiar audio, revisar `backend/orchestrator.py`, `processing.py`, `separate.py` y `speakers.py`; `backend/README.md` y `VERIFICACION.md` contienen límites y resultados medidos.
- Mantener la interfaz en español rioplatense y no presentar catálogo, pagos o publicación como funciones reales: siguen siendo demo/locales.
