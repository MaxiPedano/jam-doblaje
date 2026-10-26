<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ApiError, getSpeakers, remixJob, removeVoice, sampleMedia, studioApi, uploadVideo, type SpeakersInfo, type StudioJob, type StudioStatus, type StudioUser } from '../studio-api'
const status = ref<StudioStatus | null>(null)
const user = ref<StudioUser | null>(null)
const jobs = ref<StudioJob[]>([])
const error = ref('')
const notice = ref('')
const busy = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const file = ref<File | null>(null)
const fileInput = ref<HTMLInputElement>()
const preview = ref<string | null>(null)
const modo = ref<'voces' | 'dialogo' | 'voz'>('dialogo')
const ranges = ref('')
const editJob = ref<string | null>(null)
const editMode = ref<'voces' | 'dialogo'>('dialogo')
const editRanges = ref('')
const remixing = ref(false)
const username = ref('')
const password = ref('')
const token = ref('')
let timer: ReturnType<typeof setInterval> | undefined
let inFlight = false
let disposed = false
let uploadRequest: XMLHttpRequest | undefined
const labels: Record<StudioJob['status'], string> = { uploading: 'Recibiendo archivo', queued: 'En cola', processing: 'Procesando', voices: 'Escuchar y elegir voz', ready: 'Listo para revisar', failed: 'No se pudo completar' }
const speakersInfo = ref<Record<string, SpeakersInfo>>({})
const voiceBusy = ref(false)
function fail(e: unknown) {
  error.value = e instanceof Error ? e.message : 'No se pudo completar la operación.'
  if (e instanceof ApiError && e.status === 401) { user.value = null; jobs.value = []; preview.value = null }
}
async function refreshJobs() {
  if (!user.value || user.value.role !== 'admin' || inFlight || disposed) return
  inFlight = true
  try {
    jobs.value = await studioApi<StudioJob[]>('/jobs')
    const pending = jobs.value.filter(job => job.modo === 'voz' && ['voices', 'ready'].includes(job.status))
    for (const job of pending) {
      try { speakersInfo.value[job.id] = await getSpeakers(job.id) }
      catch (e) { if (e instanceof ApiError && e.status === 401) throw e }
    }
    for (const id of Object.keys(speakersInfo.value)) {
      if (!pending.some(job => job.id === id)) delete speakersInfo.value[id]
    }
  } catch (e) { fail(e) }
  finally { inFlight = false }
}
async function chooseVoice(job: StudioJob, target: number) {
  if (voiceBusy.value) return
  voiceBusy.value = true; error.value = ''; notice.value = ''
  try {
    await removeVoice(job.id, String(target))
    notice.value = `Cola para quitar la voz ${target}: se recombina el audio guardado sin volver a separarlo con IA.`
    await refreshJobs()
  } catch (e) { fail(e) } finally { voiceBusy.value = false }
}
async function connect() {
  busy.value = true; error.value = ''
  try {
    status.value = await studioApi<StudioStatus>('/status')
    try { user.value = await studioApi<StudioUser>('/me') }
    catch (e) { if (!(e instanceof ApiError && e.status === 401)) throw e; user.value = null }
    await refreshJobs()
  } catch (e) { fail(e) } finally { busy.value = false }
}
async function authenticate() {
  busy.value = true; error.value = ''
  try {
    user.value = await studioApi<StudioUser>(status.value?.configured ? '/login' : '/setup', 'POST',
      { username: username.value, password: password.value, ...(!status.value?.configured ? { token: token.value.trim() } : {}) })
    password.value = ''; token.value = ''
    if (status.value) status.value.configured = true
    await refreshJobs()
  } catch (e) { fail(e) } finally { busy.value = false }
}
async function logout() {
  error.value = ''
  try { await studioApi('/logout', 'POST'); user.value = null; jobs.value = []; preview.value = null }
  catch (e) { fail(e) }
}
function choose(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0] ?? null
  error.value = ''; notice.value = ''
  if (file.value && status.value && file.value.size > status.value.maxUploadBytes) { error.value = 'El archivo supera los 500 MB.'; file.value = null; if (fileInput.value) fileInput.value.value = '' }
}
async function upload() {
  if (!file.value || uploading.value) return
  uploading.value = true; uploadProgress.value = 0; error.value = ''; notice.value = ''
  try {
    const task = uploadVideo(file.value, percent => { uploadProgress.value = percent }, { modo: modo.value, ranges: ranges.value })
    uploadRequest = task.request
    await task.done
    notice.value = 'Video recibido. El servidor continúa procesándolo aunque cierres esta página.'
    file.value = null; if (fileInput.value) fileInput.value.value = ''
    await refreshJobs()
  } catch (e) { fail(e) }
  finally { uploading.value = false; uploadRequest = undefined }
}
async function retry(job: StudioJob) {
  error.value = ''
  try { await studioApi(`/jobs/${job.id}/retry`, 'POST'); await refreshJobs() } catch (e) { fail(e) }
}
function openEditor(job: StudioJob) {
  if (editJob.value === job.id) { editJob.value = null; return }
  editJob.value = job.id
  editMode.value = job.modo === 'voz' ? 'dialogo' : job.modo
  editRanges.value = job.ranges
}
async function applyRemix(job: StudioJob) {
  if (remixing.value) return
  remixing.value = true; error.value = ''; notice.value = ''
  try {
    await remixJob(job.id, editMode.value, editRanges.value)
    notice.value = 'Ajuste en cola: se recombina el audio guardado sin volver a separarlo con IA.'
    editJob.value = null
    await refreshJobs()
  } catch (e) { fail(e) } finally { remixing.value = false }
}
async function remove(job: StudioJob) {
  if (!confirm(`¿Eliminar “${job.name}”, el original y el resultado? Esta acción no se puede deshacer.`)) return
  error.value = ''
  try { await studioApi(`/jobs/${job.id}`, 'DELETE'); if (preview.value === job.id) preview.value = null; await refreshJobs() } catch (e) { fail(e) }
}
function media(job: StudioJob, variant: string, download = false) { return `/api/studio/jobs/${job.id}/media/${variant}${download ? '?download=true' : ''}` }
function sample(job: StudioJob, which: number) { return sampleMedia(job.id, which) }
onMounted(() => { connect(); timer = setInterval(refreshJobs, 2500) })
onUnmounted(() => { disposed = true; clearInterval(timer); uploadRequest?.abort() })
</script>
<template>
  <section class="page-intro"><p class="eyebrow">STUDIO · PROCESAMIENTO REAL LOCAL</p><h1>Prepará el video para doblar.</h1><p>Cargá un video, elegí qué sonido querés quitar y descargá una copia lista para preparar el doblaje.</p></section>
  <p class="notice">Hay tres formas de quitar sonido: <strong>todas las voces</strong> que detecte el modelo, <strong>solo el diálogo que marques</strong> por tramos de tiempo, o <strong>una sola voz por hablante</strong>: el sistema separa las voces, escuchás una muestra de cada una y elegís cuál quitar. En los modos por tramos y por hablante, todo lo demás se conserva: ambiente, música, efectos y voces de fondo. El modelo puede dejar restos de diálogo o alterar sonidos; el resultado se estima y conviene escucharlo. Conservamos el original y las pistas separadas para comparar y ajustar. Esta etapa no graba el nuevo doblaje ni publica automáticamente el video.</p>
  <p v-if="error" role="alert" class="notice">{{ error }}</p><p v-if="notice" role="status" class="success">{{ notice }}</p>
  <section v-if="!status" class="panel"><h2>Conectar con el servidor local</h2><p>Studio necesita el backend Python, además del servidor web.</p><code>.\.venv\Scripts\python.exe -m backend.run</code><p>Las instrucciones completas están en <code>backend/README.md</code>.</p><button :disabled="busy" @click="connect">{{ busy ? 'Conectando…' : 'Reintentar conexión' }}</button></section>
  <template v-else>
    <section v-if="!status.modelReady" class="panel"><h2>Falta preparar el modelo de IA</h2><p>Instalá las dependencias y descargá el modelo una vez. Sus archivos quedan en el almacenamiento local del equipo, fuera del repositorio.</p><pre><code>.\.venv\Scripts\python.exe -m pip install -r backend/requirements-ai.txt
.\.venv\Scripts\python.exe -m backend.manage install-model</code></pre><button :disabled="busy" @click="connect">Volver a comprobar</button></section>
    <section v-if="!status.speakerReady" class="panel"><h2>Faltan los modelos de voces por hablante</h2><p>Para el modo “Una sola voz” descargá SepFormer y ECAPA una vez. Los archivos quedan en la carpeta local DoblajeStudio, fuera del repositorio y sin cuentas externas.</p><pre><code>.\.venv\Scripts\python.exe -m backend.manage install-speaker-models</code></pre><button :disabled="busy" @click="connect">Volver a comprobar</button></section>
    <section v-if="!user" class="panel studio-login"><h2>{{ status.configured ? 'Ingresar al equipo' : 'Crear la primera cuenta del equipo' }}</h2><p>Cuenta real del backend local. Es independiente del botón “Simular vista del equipo” de la demo.</p><template v-if="!status.configured"><p>Obtené la clave de instalación desde una terminal de esta computadora:</p><code>.\.venv\Scripts\python.exe -m backend.manage setup-token</code></template><form @submit.prevent="authenticate"><div class="form-grid"><label>Usuario del equipo<input v-model="username" required minlength="3" maxlength="80" pattern="[a-zA-Z0-9_.\-]+" autocomplete="username" placeholder="Solo letras, números, punto, guion o guion bajo"></label><label>Contraseña<input v-model="password" type="password" required minlength="12" maxlength="128" :autocomplete="status.configured ? 'current-password' : 'new-password'"><small>Mínimo 12 caracteres.</small></label><label v-if="!status.configured" class="full">Clave de instalación local<input v-model="token" required type="password" autocomplete="off"></label></div><button class="primary" :disabled="busy">{{ busy ? 'Conectando…' : status.configured ? 'Ingresar' : 'Crear cuenta del equipo' }}</button></form></section>
    <template v-else>
      <section class="panel"><div class="section-heading"><h2>Sesión de {{ user.username }}</h2><button :disabled="uploading" @click="logout">Cerrar sesión del equipo</button></div><p class="muted">Sesión de 8 horas con cookie HttpOnly. Archivos privados: se necesita la sesión del equipo para verlos o descargarlos.</p></section>
      <template v-if="user.role === 'admin'">
        <section class="panel"><h2>1. Cargar video y elegir qué quitar</h2><p>MP4, MOV, MKV, WebM, M4V o AVI · máximo 500 MB y 10 minutos. Empezá con una escena de 20–30 segundos. El procesamiento usa la CPU y puede tardar más que el video.</p><form @submit.prevent="upload"><label>Video original<input ref="fileInput" type="file" accept=".mp4,.mov,.mkv,.webm,.m4v,.avi" :disabled="uploading || !status.modelReady" @change="choose"></label><p v-if="file">{{ file.name }} · {{ (file.size / 1024 / 1024).toFixed(1) }} MB</p><fieldset class="mode-field"><legend>¿Qué sonido querés quitar?</legend><label class="radio-option"><input v-model="modo" type="radio" value="dialogo" :disabled="uploading"><span><strong>Solo el diálogo que marques</strong><small>Silencia los tramos indicados y conserva el resto: ambiente, música, efectos y voces de fondo.</small></span></label><label class="radio-option"><input v-model="modo" type="radio" value="voces" :disabled="uploading"><span><strong>Todas las voces</strong><small>Quita cualquier voz que detecte el modelo. Puede llevarse también voces de fondo.</small></span></label><label class="radio-option"><input v-model="modo" type="radio" value="voz" :disabled="uploading"><span><strong>Una sola voz (por hablante)</strong><small>Separo cada hablante, escuchás una muestra de cada voz y elegís cuál quitar. Conserva ambiente, música y efectos.</small></span></label></fieldset><label v-if="modo === 'dialogo'">Tramos con diálogo (vacío = detección automática)<input v-model="ranges" placeholder="0:06-0:29, 0:35-0:41" :disabled="uploading" autocomplete="off"><small>Marcá cuándo hablan los personajes principales: inicio-fin separados por comas, en minutos:segundos. Si lo dejás vacío, se detectan los tramos de voz fuerte automáticamente y los podés ajustar después.</small></label><button class="primary controls" :disabled="!file || uploading || !status.modelReady || (modo === 'voz' && !status.speakerReady)">{{ uploading ? 'Cargando…' : modo === 'dialogo' ? 'Cargar y recortar el diálogo' : modo === 'voz' ? 'Cargar y separar las voces' : 'Cargar y quitar voces' }}</button></form><div v-if="uploading" role="status"><p>Carga del archivo: {{ uploadProgress }} %{{ uploadProgress === 100 ? ' · Confirmando recepción…' : '' }}</p><progress :value="uploadProgress" max="100"></progress><p>No cierres esta página hasta que termine la carga.</p></div></section>
        <section class="panel"><div class="section-heading"><h2>2. Revisar y descargar</h2><button @click="refreshJobs">Actualizar trabajos</button></div><p class="muted">Un trabajo se procesa a la vez. El progreso indica etapas, no una estimación de tiempo restante.</p><p v-if="!jobs.length">Todavía no cargaste videos.</p>
          <article v-for="job in jobs" :key="job.id" class="studio-job"><div class="section-heading"><div><h3>{{ job.name }}</h3><span class="badge">{{ labels[job.status] }}</span><p class="muted">{{ new Date(job.created * 1000).toLocaleString('es-AR') }}{{ job.seconds ? ' · ' + Math.round(job.seconds) + ' segundos' : '' }} · {{ job.modo === 'dialogo' ? (job.ranges ? 'Diálogo en ' + job.ranges : 'Diálogo automático') : job.modo === 'voz' ? 'Una voz por hablante' : 'Todas las voces' }}</p></div><div class="actions"><button v-if="job.status === 'ready'" @click="preview = preview === job.id ? null : job.id">{{ preview === job.id ? 'Cerrar comparación' : 'Comparar videos' }}</button><button v-if="job.status === 'ready' && job.modo !== 'voz'" @click="openEditor(job)">{{ editJob === job.id ? 'Cerrar ajuste' : 'Ajustar tramos' }}</button><button v-if="job.status === 'failed'" @click="retry(job)">Reintentar</button><button v-if="['ready', 'failed'].includes(job.status)" class="danger" @click="remove(job)">Eliminar archivos</button></div></div><p>{{ job.message }}</p><progress v-if="['queued', 'processing', 'uploading'].includes(job.status)" :value="job.progress" max="100" :aria-label="'Progreso de ' + job.name"></progress><div v-if="job.status === 'ready'" class="actions"><a class="button primary" :href="media(job, 'processed', true)">{{ job.modo === 'dialogo' ? 'Descargar video sin diálogo' : job.modo === 'voz' ? 'Descargar video sin la voz elegida' : 'Descargar video sin voces' }}</a><a class="button" :href="media(job, 'original', true)">Descargar original</a></div><div v-if="job.modo === 'voz' && ['voices', 'ready'].includes(job.status)" class="studio-voices"><p v-if="!speakersInfo[job.id]" class="muted">Cargando las voces separadas…</p><template v-else><p v-for="warning in speakersInfo[job.id].warnings" :key="warning" class="notice">{{ warning }}</p><div class="voice-options"><div v-for="voice in speakersInfo[job.id].voices" :key="voice.stream" class="voice-card"><h4>Voz {{ voice.stream }}</h4><p class="muted">{{ voice.exclusive_pct }}% del diálogo{{ voice.pitch_hz ? ' · tono de ' + voice.pitch_hz + ' Hz' : '' }}</p><audio :src="sample(job, voice.stream)" controls preload="none"></audio><button class="primary" :disabled="voiceBusy" @click="chooseVoice(job, voice.stream)">{{ job.status === 'ready' ? 'Quitar esta voz del resultado' : 'Quitar esta voz' }}</button></div></div><p class="muted">Escuchá cada muestra y elegí cuál quitar. El original y las pistas se conservan para comparar o cambiar de decisión.</p></template></div><form v-if="editJob === job.id && job.status === 'ready'" class="studio-remix" @submit.prevent="applyRemix(job)"><fieldset class="mode-field"><legend>¿Qué sonido quitar en este video?</legend><label class="radio-option"><input v-model="editMode" type="radio" value="dialogo" :disabled="remixing"><span><strong>Solo el diálogo que marques</strong><small>Se silencian los tramos indicados y se conserva todo lo demás.</small></span></label><label class="radio-option"><input v-model="editMode" type="radio" value="voces" :disabled="remixing"><span><strong>Todas las voces</strong><small>Quita cualquier voz que detecte el modelo.</small></span></label></fieldset><label v-if="editMode === 'dialogo'">Tramos con diálogo (vacío = detección automática)<input v-model="editRanges" placeholder="0:06-0:29, 0:35-0:41" :disabled="remixing" autocomplete="off"><small>Inicio-fin separados por comas. El audio ya está separado: este ajuste es rápido y no vuelve a correr la IA.</small></label><button class="primary controls" :disabled="remixing">{{ remixing ? 'Reprocesando…' : 'Reprocesar con estos tramos' }}</button></form><div v-if="preview === job.id && job.status === 'ready'" class="studio-comparison"><div><h3>Original</h3><video :src="media(job, 'original')" controls preload="metadata"></video></div><div><h3>{{ job.modo === 'voz' ? 'Sin la voz elegida · resultado estimado' : job.modo === 'dialogo' ? 'Sin diálogo · resultado estimado' : 'Sin voces · resultado estimado' }}</h3><video :src="media(job, 'processed')" controls preload="metadata"></video></div><p class="muted">Reproducí de a uno para comparar. Si el original no es compatible con el navegador, descargalo. El resultado se convierte a MP4 H.264/AAC.</p></div></article>
        </section>
      </template><p v-else class="notice">Tu cuenta no tiene permisos para cargar o procesar videos.</p>
    </template>
  </template>
  <p class="muted">Los originales, resultados, base de datos y modelos se guardan fuera del repositorio, en la carpeta local DoblajeStudio. No se envían a un servicio de separación externo. El catálogo y los planes anteriores siguen en modo demostración; Studio aún no publica contenido para suscriptores.</p>
</template>
