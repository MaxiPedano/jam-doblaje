# Memoria del proyecto

## Objetivo

Doblaje Demo combina un catálogo de doblajes con suscripciones simuladas y un Studio local para preparar videos antes de doblarlos. Studio recibe videos, separa o reduce voces con IA local, permite comparar y descarga un MP4; todavía no graba doblajes, publica contenido ni cobra.

## Arquitectura actual

- Frontend: Vue 3, TypeScript, Vite, hash routing y estado local.
- Backend: FastAPI, SQLite, autenticación real del equipo, cola local de un solo proceso, FFmpeg e IA en CPU.
- Orquestación: `backend/orchestrator.py` perfila duración, codecs, audio y video, elige el plan por modo y registra la decisión en `processing.log`.
- Datos: `%LOCALAPPDATA%\DoblajeStudio` por defecto; configurable con `DOBLAJE_DATA_DIR`.
- Modelos: Demucs `htdemucs`; modo hablantes con Silero VAD, ECAPA y SepFormer.

## Modos de Studio

- `dialogo`: separa voces/fondo y silencia tramos marcados o detectados; permite remezclar sin repetir IA.
- `voces`: quita todas las voces detectadas.
- `voz`: separa hablantes, muestra muestras y permite quitar una voz sin volver a ejecutar la IA.
- En `voz`, si VAD + ECAPA detectan un único hablante, se usa la pista vocal de Demucs directamente y se evita SepFormer. Si la detección es ambigua o hay varias voces, se usa SepFormer.
- La selección de modelos es por etapas: Demucs `htdemucs` siempre separa voz/fondo; `dialogo` aplica máscara, `voces` elimina vocals y `voz` activa ECAPA/VAD y luego SepFormer de 2 o 3 voces solo cuando hace falta.
- La estrategia de mezcla por defecto es `suma`; `resta` está disponible en `backend/speakers.py`.

## Decisiones y restricciones

- Todo el procesamiento de videos es local; no usar cuentas externas para la separación.
- No guardar videos, audio, modelos, bases SQLite, tokens ni credenciales en el repositorio.
- El backend real usa un solo worker porque la cola no es distribuida.
- La calidad de separación puede producir voces robotizadas o restos, especialmente con solapes, música fuerte y modelos de voz a 8–16 kHz.
- La estrategia `suma` suele limpiar la voz quitada usando fondo + voces conservadas; `resta` conserva más ambiente pero puede dejar artefactos.

## Estado verificado

- 16 pruebas `backend.test_backend` aprobadas.
- 13 pruebas unitarias frontend aprobadas.
- `npm run typecheck` y `npm run build` aprobados.
- 3 e2e de catálogo aprobados.
- 1 e2e Studio aprobado con IA real, incluyendo carga, separación, muestras, quitar una voz, comparación y descarga.
- El atajo de un único hablante tiene prueba específica y el mux intenta copiar el video antes de recodificarlo.
- El orquestador tiene cobertura de perfilado y selección de plan por modo.
- Backend real y frontend local se validaron en `127.0.0.1:8765` y `localhost:5173`.

## Pendientes conocidos

- La calidad auditiva de voces separadas requiere evaluación humana; aún puede haber robotización.
- El rendimiento principal sigue limitado por Demucs en CPU; la mejora de una sola voz evita la segunda separación neuronal, no Demucs.
- GPU, worker persistente y más optimizaciones son mejoras futuras, no requisitos actuales.
- El catálogo, suscripciones, pagos y publicación siguen siendo demostración/locales.

## Referencias

- Instalación y operación: `backend/README.md`.
- Resultados comprobados y pendientes: `VERIFICACION.md`.
- Tests backend: `backend/test_backend.py`.
- Pipeline de procesamiento: `backend/processing.py`, `backend/separate.py`, `backend/speakers.py`.
