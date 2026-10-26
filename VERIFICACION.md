# Verificación — suscripciones de Jam de doblaje

## Studio real local — nueva etapa

- Instalados en este equipo Python/entorno virtual, FFmpeg y Demucs `htdemucs`; modelo descargado fuera del repositorio.
- **16 pruebas de backend aprobadas:** creación con clave de instalación, login, sesión y logout, rechazo de orígenes no permitidos, permisos de suscriptor, privacidad entre cuentas, límites de carga/cola, descarga por rangos, reintento, rechazo de archivo inválido con FFmpeg real, validación de los modos/tramos de diálogo, detección automática de tramos y máscara con fundidos, remezcla sobre pistas guardadas (con FFmpeg real y sin volver a ejecutar la IA), las 6 del modo “Una sola voz” y el perfilado/selección del plan del orquestador.
- **Smoke test de IA aprobado:** video sintético de 2 segundos → carga autenticada → extracción FFmpeg → separación Demucs real → MP4 H.264/AAC → descarga verificada.
- **Prueba integral de Studio en Chromium aprobada (`npm run test:studio`, 1,2 min):** creación de cuenta en servidor temporal, carga de video sintético con tramos de diálogo explícitos, IA real, mensaje de tramos recortados, persistencia tras recarga, comparación de original/resultado, **ajuste de tramos en vivo (remezcla sin IA)**, lectura de metadatos del MP4, descarga y bloqueo sin sesión/después de logout; **más la secuencia del modo hablante:** segunda carga como “Una sola voz”, badge “Escuchar y elegir voz”, **2 tarjetas de voz con muestras**, aviso de segunda voz no clara (voces sintéticas), “Quitar esta voz” sin re-ejecutar IA, link de descarga privada, re-intento desde el resultado y comparación.
- Las pruebas rápidas de API sustituyen el worker salvo donde se indica FFmpeg real. La prueba integral usa el worker y modelo reales, sin sustituir el procesamiento.
- Se corrigió el escaneo de Vite para excluir `.venv` y limitar la búsqueda de entradas a `index.html`, después de observar demoras al instalar Python dentro del proyecto. Las ejecuciones finales de catálogo y Studio completaron correctamente. Studio tardó 40,5 segundos en su recorrido integral sintético; esto no mide rendimiento de escenas largas.

**Primera escena real procesada (medición de nivel, no auditiva):** `2026-10-24 22-50-49.mp4` (38,7 s, 1080p60) en modo diálogo con detección automática → 12 tramos (0:05.9 a 0:28.9), 94,3 % de la energía vocal recortada. Medido sobre el resultado: dentro de los tramos el nivel bajó de −40,3 dB a −84,2 dB (el diálogo queda prácticamente en silencio) y fuera de los tramos se mantuvo −56,0 → −56,1 dB con correlación 0,9924 respecto del original (pausas, cabezal y cola intactos). La escena casi no contiene música ni efectos, por lo que la pista de fondo quedó casi en silencio: cualquier sonido exterior que ocurra **dentro** de un tramo marcado se elimina junto con el diálogo. **Falta la revisión auditiva del equipo** para confirmar si los sonidos de exterior que se quieren conservar siguen presentes y si el diálogo desaparece del todo.

**Modo “Una sola voz” (separación por hablante) — medición técnica, falta la escucha del equipo:** con la escena real `2026-10-25 00-17-21.mp4` (20,4 s) se evaluaron dos modelos de SepFormer: `sepformer-whamr16k` **sí separa** (dos voces con armónicos claros: pitch strength 0,36 a 256 Hz y 0,71 a 364 Hz contra 0,01 del ruido; turnos alternados voz B 4–13 s y voz A 11–20 s; ~100 s de separación en CPU, ≈5× tiempo real) y `sepformer-wsj02mix` **colapsó** (correlación −0,975 entre un stream y la mezcla), por lo que se descartó por métrica y no por oído. El clustering con ECAPA+AHC sobre las voces separadas identifica 2 hablantes correctamente. El pipeline completo (VAD Silero → ECAPA → AHC → SepFormer → muestras → suma/resta → mux) corrió de punta a punta sobre una copia del trabajo real y sobre el e2e con voces sintéticas. **Pendiente: que el equipo escuche `Videos\prueba-quitar-voz`** (4 MP4 sincronizados: quitar voz A/B × suma/resta, más las 2 muestras) para confirmar whamr16k y elegir la estrategia activa (`suma` por defecto).

**No se evaluó todavía la calidad auditiva con diálogos de una película.** El resultado verifica funcionamiento técnico y niveles, no percepción subjetiva. Pendientes: revisión auditiva de la escena procesada y de las 4 variantes del modo hablante, grabar/mezclar un nuevo doblaje, publicación desde Studio, cuentas de suscriptores, pagos reales y despliegue del backend.

Studio sí tiene autenticación y permisos de descarga reales para el equipo; las limitaciones de suscripción local que se describen abajo siguen aplicando al catálogo demo.

## Ejecutado y aprobado

- `npm run typecheck`: sin errores.
- `npm test`: **13 pruebas aprobadas**, en 2 archivos.
- `npm run build`: build estático generado correctamente en `dist`.
- `npm run test:e2e`: **3 pruebas aprobadas** en Chromium.
- `python -m unittest backend.test_backend`: **16 pruebas aprobadas** (9 originales + 6 del modo hablante/optimización + 1 del orquestador).
- `npm run test:studio`: **1 prueba integral aprobada** (2,5 min, IA real, incluye el flujo del modo hablante).

## Cobertura de lógica

- Búsqueda por título/película sin distinguir acentos y mayúsculas, filtro por género.
- Alta, edición, eliminación, persistencia y limpieza de favoritos/lista.
- JSON exportable/reimportable, datos inválidos, IDs duplicados, protocolos y proveedores permitidos.
- Migración de metadatos antiguos y popularidad ausente a alta/Premium.
- **Las nueve combinaciones** entre Básico/Estándar/Premium y popularidad baja/media/alta.
- Ningún nivel permite reproducir sin suscripción o con fecha vencida.
- Vencimiento mensual absoluto, recarga por serialización y fin de mes.
- Actualización de acceso al cambiar de plan, editar popularidad o vencer.
- Recuperación del catálogo inicial ante almacenamiento corrupto.

## Recorridos de navegador

1. **Equipo y suscriptor:** cambio de vista, carga y edición de un doblaje, selección de popularidad, descarga y lectura del JSON, eliminación y reimportación; rechazo de un archivo inválido; búsqueda por película, favoritos y lista.
2. **Suscripción y enlaces:** bloqueo anónimo y con Básico para un video Premium; habilitación con Premium y persistencia tras recarga. Se abre el enlace en un contexto de navegador independiente con el mismo catálogo y sin suscripción: no se monta el reproductor. Vencimiento simulado, desmontaje y bloqueo tras recarga.
3. **Jerarquía y HTML5:** filtro de disponibles con 1, 2 y 3 videos para Básico, Estándar y Premium respectivamente. Montaje de HTML5 con Premium y desmontaje al bajar a Básico. Página de ID inexistente sin reproductor.
4. **Vista móvil simulada:** sin desbordamiento horizontal a 390 × 844 en catálogo, acceso, vista personal y carga del equipo.

## Qué estuvo simulado

- Suscripciones, roles y popularidad editorial: estado local. No hay usuarios autenticados ni cobros.
- Drive: respuesta ficticia interceptada, sin reproducir contenido externo.
- HTML5: URLs sintéticas bloqueadas; se prueba la presencia del reproductor, no códecs ni reproducción.
- Celular: viewport de Chromium, no dispositivo físico.

## Pendiente

- Importes y moneda de los tres planes.
- Cuentas de suscriptores y suscripciones validadas por backend, publicación desde Studio y administración de múltiples cuentas del equipo. Studio ya autentica la primera cuenta del equipo y protege sus trabajos.
- Pagos reales y almacenamiento de videos con acceso controlado. El bloqueo local no protege los enlaces externos.
- Reproducción real de Drive con archivos autorizados, permisos, cookies, procesamiento y cuotas.
- Reproducción HTML5 real, códecs y encabezados del servidor.
- Televisores, mandos, iOS/Safari, Android, pantalla completa y dispositivos físicos grandes.
- Prueba de retorno tras suspensión prolongada en dispositivos reales; la aplicación recalcula al recuperar foco/visibilidad.
- Publicación real en Pages y comprobación de enlaces desde otra computadora. No se ejecutó el workflow ni se publicó nada.
- Revisión visual manual exhaustiva y lector de pantalla.
