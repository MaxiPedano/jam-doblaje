<script setup lang="ts">
import { reactive, ref } from 'vue'
import { authError, catalog, profile, removeVideo, replaceCatalog, saveVideo, teamMode } from '../store'
import { minimumPlan, parseCatalog, plans, popularityPlans, validateVideo, type Video } from '../domain'
import { supabaseConfigured } from '../lib/supabase'
const blank = (): Video => ({ id: '', titulo: '', pelicula: '', genero: '', popularidad: 'alta', miniatura: '', proveedor: 'google-drive', fuente: '' })
const form = reactive(blank())
const editing = ref(false)
const message = ref('')
const error = ref('')
function clear() { Object.assign(form, blank()); editing.value = false }
function edit(v: Video) { Object.assign(form, blank(), v); editing.value = true; document.querySelector('#scene-form')?.scrollIntoView({ behavior: 'smooth' }) }
function save() {
  error.value = ''; message.value = ''
  try {
    if (form.proveedor !== 'google-drive') throw new Error('El proveedor HTML5 está en desarrollo. Usá Google Drive.')
    saveVideo(validateVideo({ ...form, id: editing.value ? form.id : crypto.randomUUID() }))
    message.value = editing.value ? 'Doblaje actualizado.' : 'Doblaje agregado.'
    clear()
  } catch (e) { error.value = (e as Error).message }
}
async function remove(v: Video) {
  if (!confirm(`¿Eliminar “${v.titulo}”? También se quitará de favoritos y de la cola.`)) return
  await removeVideo(v.id)
  if (form.id === v.id) clear()
  message.value = 'Doblaje eliminado.'
}
function exportJson() {
  const url = URL.createObjectURL(new Blob([JSON.stringify({ version: 1, videos: catalog.value }, null, 2)], { type: 'application/json' }))
  const a = document.createElement('a'); a.href = url; a.download = 'catalog.json'; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  message.value = 'Exportación solicitada. Revisá las descargas del navegador.'
}
async function importJson(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  error.value = ''; message.value = ''
  try {
    if (!file) return
    if (file.size > 5 * 1024 * 1024) throw new Error('El JSON no debe superar 5 MB.')
    const next = parseCatalog(JSON.parse(await file.text()))
    if (!confirm(`¿Reemplazar el catálogo por ${next.videos.length} doblajes? Exportá primero si querés conservar el actual.`)) return
    replaceCatalog(next.videos); clear(); message.value = `Catálogo importado: ${next.videos.length} doblajes.`
  } catch (e) { error.value = `No se importó: ${(e as Error).message}` }
  finally { input.value = '' }
}
</script>
<template>
  <section v-if="!teamMode && !(supabaseConfigured && profile?.role === 'admin')" class="panel"><h1>Carga del equipo</h1><p>El catálogo lo publica el equipo. La vista de suscriptor no incluye herramientas de carga.</p><p class="notice">Iniciá sesión con una cuenta con rol de administrador para cargar doblajes.</p></section>
  <template v-else>
  <section class="page-intro"><p class="eyebrow">CONTENIDO DEL EQUIPO</p><h1>Carga de doblajes</h1><p>Agregá videos con el doblaje terminado y elegí su popularidad para asignar el plan mínimo.</p></section>
  <div class="notice">Google Drive es el único proveedor activo. Los cambios se guardan en Supabase cuando el proyecto está configurado; HTML5 y la carga directa de archivos quedan en desarrollo.</div>
  <section class="panel"><h2>Proveedores</h2><p><b>Google Drive</b> está activo para reproducir los doblajes publicados.</p><p class="muted"><b>Video directo HTML5</b>, Cloudflare Stream y carga directa de archivos: en desarrollo.</p></section>
  <section class="panel instructions"><h2>Publicar un doblaje en la demo</h2><ol><li>Prepará el video con el doblaje terminado y subilo a Google Drive. La demo no graba voces ni procesa el video.</li><li>Configurá sus permisos en Drive. En esta demo los enlaces externos no están protegidos por la suscripción; antes de cobrar se necesita otro sistema de acceso.</li><li>Pegá el enlace, completá los datos y elegí la popularidad. Baja requiere Básico; media, Estándar; alta, Premium. La clasificación la decide el equipo.</li></ol><p class="muted">Los registros importados sin popularidad se asignan a alta (Premium) hasta que el equipo los revise.</p></section>
  <p v-if="message" class="success" role="status">{{ message }}</p><p v-if="error || authError" class="notice" role="alert">{{ error || authError }}</p>
  <form id="scene-form" class="panel" @submit.prevent="save"><h2>{{ editing ? 'Editar doblaje' : 'Agregar doblaje' }}</h2><div class="form-grid"><label>Título del doblaje<input v-model="form.titulo" required maxlength="160" placeholder="La despedida en la estación"></label><label>Película<input v-model="form.pelicula" required maxlength="160" placeholder="Nombre de la película"></label><label>Género<input v-model="form.genero" required maxlength="60" placeholder="Comedia, drama, acción…"></label><label>Popularidad<select v-model="form.popularidad"><option value="baja">Baja · Básico</option><option value="media">Media · Estándar</option><option value="alta">Alta · Premium</option></select><small>Plan mínimo: {{ plans[popularityPlans[form.popularidad]].nombre }}. Los planes superiores también lo incluyen.</small></label><label>Proveedor<select v-model="form.proveedor"><option value="google-drive">Google Drive · vista previa</option><option value="html5">Video directo · HTML5</option></select></label><label class="full">{{ form.proveedor === 'google-drive' ? 'Enlace de archivo de Drive o identificador' : 'URL HTTPS directa del video' }}<input v-model="form.fuente" required maxlength="2048" :placeholder="form.proveedor === 'google-drive' ? 'Pegá el enlace compartido del archivo' : 'Pegá una URL HTTPS de un archivo reproducible'"><small v-if="form.proveedor === 'html5'">Debe responder con video compatible (por ejemplo MP4 o WebM), no con una página web.</small></label><label class="full">Miniatura (opcional, URL HTTPS)<input v-model="form.miniatura" type="url" maxlength="2048" placeholder="Sin miniatura se muestra una ilustración"></label></div><div class="actions"><button class="primary" type="submit">{{ editing ? 'Guardar cambios' : 'Agregar doblaje' }}</button><button v-if="editing" type="button" @click="clear">Cancelar edición</button></div></form>
  <section class="panel"><div class="section-heading"><h2>Catálogo de doblajes <span class="count">{{ catalog.length }}</span></h2><div class="actions"><button @click="exportJson">Exportar JSON</button><label class="button import-button">Importar JSON<input type="file" accept=".json,application/json" @change="importJson"></label></div></div><p class="muted">La importación reemplaza el catálogo tras validar el archivo y pedir confirmación. No incluyas videos, base64 ni credenciales.</p><p v-if="!catalog.length">Todavía no hay doblajes configurados.</p><ul class="management-list"><li v-for="video in catalog" :key="video.id"><span><b>{{ video.titulo }}</b><small>{{ video.pelicula }} · {{ video.genero }} · Popularidad {{ video.popularidad }} · Desde {{ plans[minimumPlan(video)].nombre }}</small></span><div class="actions"><RouterLink class="button" :to="'/doblaje/' + video.id">Ver página / compartir</RouterLink><button @click="edit(video)">Editar<span class="sr-only"> {{ video.titulo }}</span></button><button class="danger" @click="remove(video)">Eliminar<span class="sr-only"> {{ video.titulo }}</span></button></div></li></ul></section>
  </template>
</template>
