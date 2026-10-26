<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { catalog, currentVideo, selected } from '../store'
const route = useRoute()
const message = ref('')
watch(() => route.params.id, id => { selected.value = typeof id === 'string' ? id : null; message.value = '' }, { immediate: true })
const shareUrl = computed(() => {
  const url = new URL(window.location.href)
  url.hash = `/doblaje/${encodeURIComponent(String(route.params.id))}`
  return url.href
})
async function copy() {
  try { await navigator.clipboard.writeText(shareUrl.value); message.value = 'Enlace copiado.' }
  catch { message.value = 'No se pudo copiar automáticamente. Seleccioná y copiá el enlace del campo.' }
}
</script>
<template>
  <section class="page-intro"><p class="eyebrow">DOBLAJES DEL EQUIPO</p><h1>{{ currentVideo ? 'Una historia para volver a ver.' : 'Doblaje no disponible' }}</h1></section>
  <section v-if="currentVideo" class="panel"><h2>Compartir este doblaje</h2><p>El destinatario necesita una suscripción activa que incluya este video. El enlace no regala acceso.</p><label>Enlace para compartir<input :value="shareUrl" readonly @focus="($event.target as HTMLInputElement).select()"></label><button class="controls" @click="copy">Copiar enlace</button><p v-if="message" role="status">{{ message }}</p><p class="muted">Demo local: el destinatario necesita el mismo catálogo y una dirección accesible. Un enlace a localhost solo funciona en tu computadora. Exportá el catálogo y volvé a desplegar para compartir contenido actualizado.</p></section>
  <section v-else class="empty panel"><h2>No encontramos este video en el catálogo.</h2><p>{{ catalog.length ? 'Puede haber sido eliminado o el enlace no corresponde a este catálogo.' : 'Todavía no hay doblajes cargados en este navegador.' }}</p><RouterLink class="button primary" to="/">Volver al catálogo</RouterLink></section>
</template>
