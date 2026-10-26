# Studio local: carga real y separación de voces

Esta es la primera parte del backend real. **Studio recibe archivos, guarda trabajos en SQLite, autentica al equipo y ejecuta FFmpeg + Demucs para generar un MP4 con el audio no vocal estimado.** No es un botón simulado. El catálogo público, los planes y pagos anteriores siguen siendo una demo independiente.

## Preparación en Windows

Probado con Python 3.13.6, Node.js 22 y CPU. Desde la carpeta del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-ai.txt
.\.venv\Scripts\python.exe -m backend.manage install-model
.\.venv\Scripts\python.exe -m backend.manage install-speaker-models
```

`install-model` prepara Demucs (necesario para todos los modos). `install-speaker-models` descarga además SepFormer (separación de 2 y 3 voces) y ECAPA (huellas vocales), unos 300 MB adicionales, solo para el modo **Una sola voz**; se descargan desde Hugging Face **sin cuentas ni tokens**. Si no lo instalás, los demás modos siguen funcionando y Studio te avisa si intentás usar el modo de hablante.

La primera instalación descarga varios cientos de MB de dependencias y aproximadamente 80 MB de pesos de `htdemucs`. Puede demorar según la conexión y el antivirus. FFmpeg viene incluido con `imageio-ffmpeg`: no hace falta instalarlo globalmente. Se recomienda disponer de varios GB libres y al menos 8 GB de RAM; la velocidad depende de la computadora. Esta versión usa CPU, no requiere GPU ni servicios pagos.

Los modelos se descargan desde el origen de Demucs durante la preparación. El contenido de los videos no se envía a un servicio externo de separación. Una vez preparado el modelo, se procesa localmente.

En macOS/Linux usá `.venv/bin/python` en lugar de `.\.venv\Scripts\python.exe`; esa combinación no se probó en esta entrega.

## Iniciar los dos servidores

Terminal 1, backend:

```powershell
.\.venv\Scripts\python.exe -m backend.run
```

Terminal 2, frontend:

```powershell
npm run dev -- --port 5173 --strictPort
```

Abrí **http://localhost:5173/#/studio**. Vite reenvía `/api` al backend en `127.0.0.1:8765`. El backend escucha solo en loopback. La lista de orígenes admitidos y el proxy están preparados para los puertos locales documentados; no expongas esta configuración como servidor público.

## Crear tu cuenta del equipo

1. En una terminal local ejecutá:

   ```powershell
   .\.venv\Scripts\python.exe -m backend.manage setup-token
   ```

2. Copiá la **clave de instalación** que muestra y abrí Studio.
3. Elegí un usuario de al menos 3 caracteres (letras, números, punto, guion o guion bajo), una contraseña de al menos 12 caracteres y pegá la clave de instalación.
4. Pulsá **Crear cuenta del equipo**. Esa clave deja de funcionar cuando se crea la cuenta. Las próximas veces iniciá sesión con tu usuario y contraseña.

No hay credenciales predeterminadas. La contraseña se guarda como hash scrypt con sal; la sesión es una cookie HttpOnly/SameSite Strict con vencimiento de 8 horas y token almacenado como hash. Cerrar sesión revoca el token en el servidor. La cuenta de Studio es independiente de “Simular vista del equipo”. Cambiar ese botón o el localStorage no permite subir ni descargar archivos privados de Studio.

La creación inicial requiere acceso a la computadora y a esa clave. El backend controla roles y propiedad de trabajos. Se limita el número de intentos de inicio de sesión. Esta fase admite crear la primera cuenta de equipo; la administración de más cuentas y la recuperación de contraseña quedan para la siguiente etapa.

## Cargar y procesar

1. Ingresá en Studio, seleccioná **Video original** y elegí qué sonido quitar:
   - **Solo el diálogo que marques** (recomendado para doblaje): se silencian los tramos indicados y se conserva todo lo demás.
   - **Todas las voces**: quita cualquier voz que detecte el modelo.
   - **Una sola voz (por hablante)**: separa cada hablante, te deja escuchar una muestra de cada voz y elegís cuál quitar.
2. En el modo de diálogo, completá **Tramos con diálogo** con `inicio-fin` separados por comas, por ejemplo `0:06-0:29, 0:35-0:41`. Si lo dejás vacío, **se detectan los tramos de voz fuerte automáticamente** y quedan guardados en el trabajo para que puedas ajustarlos.
3. Pulsá **Cargar y recortar el diálogo** (o **Cargar y quitar voces** / **Cargar y separar las voces** según el modo) y esperá a que termine la carga antes de cerrar la página. Después, el trabajo sigue en el backend aunque cierres el navegador.
4. Mirá el progreso por etapas: cola → validación/extracción → separación IA → generación MP4.
5. Cuando esté listo, pulsá **Comparar videos**. Reproducí el original y el resultado de a uno; no se sincronizan automáticamente.
6. Con **Ajustar tramos** volvés a combinar el audio con otros tramos **sin volver a ejecutar la IA**: las pistas separadas se conservan y la mezcla tarda segundos. En el modo de hablante, el equivalente es **Quitar esta voz**, que recombina sin repetir la separación.
7. Descargá el resultado. El archivo original también se conserva y se puede descargar.

Límites actuales:

- Hasta 500 MB y 10 minutos por archivo; empezá con 20–30 segundos.
- Contenedores MP4, MOV, MKV, WebM, M4V o AVI con video y audio decodificables.
- La extensión no basta: el contenido se valida con FFmpeg. Se rechazan playlists, archivos vacíos, sin audio, corruptos y duración inválida.
- Una tarea a la vez y hasta tres cargas/trabajos en curso. Se exigen 2 GB libres al aceptar un trabajo; los archivos históricos pueden ocupar espacio hasta que los elimines.
- El porcentaje representa etapas, no tiempo exacto restante. Demucs puede pasar mucho tiempo en la fase de separación, especialmente con CPU.
- Tiempos máximos para las etapas, incluido un máximo de dos horas para la separación. Al fallar se conserva el original y se puede reintentar.
- Al reiniciar el servidor, los trabajos interrumpidos quedan como fallidos con opción de reintentar, no se muestran como completados.
- El botón **Eliminar archivos** borra original, resultado y registro tras confirmación. No se permite eliminar mientras se procesa.

El resultado es MP4 H.264/AAC para facilitar reproducción en navegador. Se conserva el tamaño del video y se usa el audio procesado; no es una copia bit a bit del video original. Los subtítulos/otras pistas no se copian. La duración del resultado se limita a la pista de audio extraída: videos con audio más corto que la imagen pueden terminar antes. El original permanece disponible.

## Orquestador de procesamiento

Antes de extraer el audio, `backend/orchestrator.py` perfila el archivo con FFmpeg y construye un plan según el modo:

- `dialogo`: `htdemucs` + máscara por tramos.
- `voces`: `htdemucs` + eliminación de la pista vocal.
- `voz`: `htdemucs` + VAD/ECAPA; SepFormer se usa solo si el análisis indica más de un hablante.

El plan queda registrado en `processing.log`, junto con codec, duración, frecuencia y canales detectados. La salida intenta copiar el stream de video (`-c:v copy`) y solo recodifica a H.264 si el contenedor o codec no son compatibles. La cola sigue siendo de un solo worker: el orquestador organiza muchos trabajos, pero no ejecuta IA pesada en paralelo.

## Qué significa “quitar el diálogo”

Demucs `htdemucs` separa `vocals`, `drums`, `bass` y `other`. En el modo **todas las voces** se suman las tres pistas no vocales y ese audio se vuelve a unir al video.

En el modo **diálogo**, el modelo se ejecuta igual pero se conservan las dos pistas: `stems/vocals.wav` y `stems/background.wav`. La salida es `fondo + voces × máscara`, donde la máscara vale 0 dentro de los tramos marcados y 1 fuera, con fundidos de 60 ms para evitar cortes secos. Así:

- Dentro de los tramos se quita la voz (principal y cualquier otra voz presente ahí).
- Fuera de los tramos el audio se conserva tal cual: pausas, cabezales, colas, música, efectos y voces de fondo.
- Si hay música o efectos por debajo del diálogo, aparecen en la pista de fondo y **se mantienen durante los tramos**.

La detección automática marca los tramos donde el nivel vocal supera los 22 dB del pico con un piso de −60 dB; es una sugerencia, no una segmentación por hablante. **No distingue un protagonista concreto dentro de un tramo:** si dentro del mismo tramo hay otra voz que querés conservar, se quita también. En escenas casi sin música (por ejemplo, grabación de acento con diálogo dominante) la pista de fondo queda casi en silencio y el tramo marcado se escucha muy bajo: revisá siempre el resultado y ajustá los tramos.

**Demucs está entrenado con música, no con diálogos de películas.** Puede dejar restos de voz o alterar efectos. No promete una pista M&E perfecta; si se dispone de música y efectos separados originales, esa fuente es preferible. Antes de usar el resultado revisá su calidad con una escena representativa.

Esta fase **no graba un doblaje nuevo, no mezcla la voz de un usuario ni publica el resultado para suscriptores**. Genera el material base para preparar el doblaje. Se puede descargar y trabajar externamente; después el equipo puede agregar su doblaje terminado al catálogo demo por enlace.

## Qué significa “una sola voz (por hablante)”

Este modo es distinto a los anteriores: en lugar de recortar tramos, **separa a los hablantes entre sí** y después podés elegir cuál quitar. Todo local, sin cuentas ni servicios externos. El pipeline es:

1. **Silero VAD** detecta dónde hay voz en el audio extraído del video.
2. **ECAPA (SpeechBrain)** calcula una huella vocal por segmento; un clustering aglomerativo agrupa las huellas por similitud (sin saber de antemano cuántos hablantes hay).
3. **SepFormer (`speechbrain/sepformer-whamr16k`)** separa la señal en pistas independientes, una por hablante. Con exactamente 3 grupos se usa el modelo de 3 voces (`sepformer-wsj03mix`); con 2 o más, se separa en 2 pistas y se agrupan por correlación con los turnos de voz.
4. Se guardan en `stems/`: `speaker-1.wav`, `speaker-2.wav`, una muestra escuchable de cada uno (`sample-1.wav`, `sample-2.wav`) y `speakers.json` con los turnos y avisos.
5. En la interfaz escuchás las muestras y pulsás **Quitar esta voz**. El resultado se arma sumando el fondo (música/efectos) con las voces que conservás, y se reutilizan las pistas ya separadas: **no se repite la IA**.

Cuando VAD + ECAPA detectan un único hablante, se usa un atajo: la pista vocal de Demucs se convierte directamente en una sola voz y no se ejecuta SepFormer. Así, una escena de una voz con música evita la segunda separación neuronal, que es la etapa más lenta. Si el análisis es ambiguo o detecta varios hablantes, se conserva el pipeline completo.

También existe la estrategia alternativa `resta` (`original − voz quitada`), que puede preservar mejor el ambiente en algunos casos pero dejar restos de la voz quitada. La estrategia activa está en `STRATEGY` dentro de `backend/speakers.py` (por defecto `suma`).

Límites importantes:

- **SepFormer está entrenado en voz aislada con ancho de banda de telefonía (8–16 kHz).** Música fuerte, gritos o solapes simultáneos de dos voces degradan la separación; puede quedar un leve “efecto vocoder”.
- **Si los dos hablantes hablan al mismo tiempo, la separación es peor.** `speakers.json` incluye `both_strong_pct` y un aviso cuando hay solape.
- Si el VAD o la detección de pitch no encuentran una segunda voz clara, se muestra igual con el aviso *“No encontré una segunda voz clara”*; revisá las muestras antes de quitar nada.
- Con 4 o más hablantes la calidad baja: se separan 2 pistas y se agrupan; el caso de 3 se detecta y usa el modelo de 3 voces.
- **Tiempos en CPU:** con varias voces, la separación demora alrededor de 5× la duración del video en esta máquina (un clip de 20 s tardó ~100 s, más los ~60 s de Demucs). Una sola voz puede usar el atajo y evitar esos ~100 s adicionales. Planificá cargas de varios minutos si hay varios hablantes.
- La voz resultante no se sintetiza ni se “dubla”: es la voz que conservaste, sin la otra, con música y efectos del fondo.

## Dónde se guarda

Por defecto en Windows: `%LOCALAPPDATA%\DoblajeStudio`. Incluye:

- `studio.sqlite3`: cuentas, sesiones y estado de trabajos.
- `models/`: pesos del modelo.
- `models/speakers/`: pesos de SepFormer y ECAPA (si instalaste `install-speaker-models`).
- `jobs/<UUID>/original`: archivo subido, con nombre interno generado.
- `jobs/<UUID>/processed.mp4`: resultado.
- `jobs/<UUID>/stems/`: pistas separadas (`vocals.wav`, `background.wav` y, en detección automática, `detected-ranges.json`); en el modo de hablante, `speaker-1/2.wav`, `sample-1/2.wav` y `speakers.json`. Permiten ajustar tramos o cambiar de voz sin repetir la IA y ocupan unos 21 MB por minuto de audio.
- `jobs/<UUID>/processing.log`: diagnóstico de procesos.

Los WAV intermedios (`audio.wav`, `mixed.wav`, `ranges.json`) se eliminan al finalizar; las pistas `stems/` se conservan hasta que eliminás el trabajo. Los archivos nunca se guardan en `src`, `public`, localStorage o base64. No están expuestos en una carpeta estática; el servidor verifica sesión, rol y dueño en cada descarga y solicitud de rango.

Podés consultar la ubicación con `python -m backend.manage path`, usando el intérprete del entorno virtual. Para elegir otra ubicación, definí `DOBLAJE_DATA_DIR` **fuera del repositorio** antes de ejecutar preparación y servidor. Respaldá SQLite y los videos con el servidor detenido. No cambies la ubicación sin copiar los datos que quieras conservar.

## Diagnóstico

- **Backend no disponible:** iniciá `backend.run` y comprobá `http://127.0.0.1:8765/api/studio/status`.
- **Modelo no preparado:** ejecutá `backend.manage install-model` en el mismo entorno y directorio de datos que usa el servidor.
- **Modelos de voz no preparados:** el estado incluye `speakerReady: false` y Studio muestra el comando; ejecutá `backend.manage install-speaker-models`. El resto del Studio funciona igual.
- **Procesamiento fallido:** revisá `processing.log` en la carpeta del trabajo; probá un fragmento corto MP4 con audio. No subas el log públicamente si contiene rutas o nombres privados.
- **Original no se reproduce en navegador:** algunos contenedores/códecs no son compatibles; descargalo. El resultado se convierte a H.264/AAC.
- **Sesión vencida:** volvé a ingresar; el trabajo continúa en el servidor.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m unittest backend.test_backend -v
.\.venv\Scripts\python.exe -m backend.smoke_ai
npm run test:studio
```

- Las pruebas de API usan SQLite temporal y comprueban autenticación, roles, privacidad por dueño, CSRF, sesión, límites, reintento, descarga por rangos, los modos de carga con tramos de diálogo, la validación de tramos, la detección automática con máscara, la remezcla sobre pistas guardadas, el modo de hablante (subida sin modelos → 503, endpoints de voces/muestras/quitar, migración del esquema y combinación de estrategias suma/resta). La cola se sustituye en las pruebas rápidas; la validación de archivo inválido, la remezcla y la prueba de detección de tramos sí ejecutan FFmpeg o NumPy reales.
- `smoke_ai` crea un video sintético de 2 segundos y ejecuta el modelo real hasta la descarga del MP4. Usa datos temporales; no modifica las cuentas reales.
- `test:studio` abre Chromium, crea una cuenta en un servidor de prueba aislado, carga un video sintético, ejecuta IA real (modo diálogo y modo hablante con voces sintéticas: separación, dos muestras, quitar una voz, comparar y descarga privada), recarga, compara y verifica el bloqueo sin sesión. Requiere el navegador de Playwright y los modelos instalados.
- `backend.browser_server` es solo para pruebas; no usarlo como servidor real. Su clave de instalación conocida y el endpoint de video sintético solo existen en ese servidor temporal.

## Producción y siguiente etapa

Este backend está preparado para **uso local de un equipo**, con un solo proceso de servidor. No usar varios workers con esta cola ni exponerlo directamente a Internet. La siguiente etapa requiere HTTPS y cookies Secure, despliegue/configuración de orígenes, cola durable con workers aislados, cuotas por usuario y control operativo; además de cuentas de suscriptores, catálogo central, publicación, pagos y autorización por plan. El aislamiento actual es autenticación de aplicación, no un sandbox para videos hostiles.

GitHub Pages no ejecuta Python, FFmpeg ni IA. Puede seguir mostrando el frontend de demostración; Studio necesita este backend. No se publicó ni contrató ningún servicio.
