<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { access, active, allowed, authError, currentVideo, profile, refreshClock, storageWarning, teamMode, timeLeft } from './store'
import { minimumPlan, plans, providers } from './domain'
import { supabaseConfigured } from './lib/supabase'
const player = ref<HTMLElement>()
const route = useRoute()
const fullscreenError = ref('')
const mediaError = ref(false)
const large = ref(false)
const clock = computed(() => {
  const seconds = Math.ceil(timeLeft.value / 1000)
  return `${Math.floor(seconds / 3600).toString().padStart(2, '0')}:${Math.floor(seconds % 3600 / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`
})
let timer: ReturnType<typeof setInterval>
onMounted(() => {
  timer = setInterval(refreshClock, 1000)
  window.addEventListener('focus', refreshClock)
  document.addEventListener('visibilitychange', refreshClock)
})
onUnmounted(() => {
  clearInterval(timer)
  window.removeEventListener('focus', refreshClock)
  document.removeEventListener('visibilitychange', refreshClock)
})
async function fullscreen() {
  fullscreenError.value = ''
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
    else if (player.value?.requestFullscreen) await player.value.requestFullscreen()
    else fullscreenError.value = 'Este navegador no permite pantalla completa. Probá el modo pantalla grande.'
  } catch { fullscreenError.value = 'El navegador no permitió la pantalla completa.' }
}
</script>

<template>
  <div :class="{ 'large-mode': large }">
    <div class="demo-banner">Modo demostración: sin cobros reales</div>
    <header class="header shell">
       <RouterLink to="/" class="brand"><span class="brand-icon">▶</span><span>Jam <b>de doblaje</b><small>HISTORIAS CON OTRA VOZ.</small></span></RouterLink>
      <nav aria-label="Navegación principal">
        <RouterLink to="/">Catálogo</RouterLink><RouterLink to="/mis-escenas">Mis doblajes</RouterLink><RouterLink to="/acceso">Cuenta y planes</RouterLink><RouterLink to="/studio">Studio · En desarrollo</RouterLink><RouterLink v-if="teamMode || profile?.role === 'admin'" to="/configuracion">Carga del equipo</RouterLink>
      </nav>
    </header>
    <main class="shell">
       <p v-if="storageWarning" class="notice" role="alert">{{ storageWarning }}</p>
       <p v-if="authError" class="notice" role="alert">{{ authError }}</p>
      <div v-if="route.path !== '/studio'" class="session-strip"><span><i :class="{ live: active }"></i>{{ active && access ? 'Suscripción ' + plans[access.plan].nombre + ' activa' : access ? 'Suscripción vencida' : 'Suscribite para ver los doblajes.' }}</span><RouterLink to="/acceso">{{ active ? clock + ' restantes' : 'Ver planes →' }}</RouterLink></div>
      <RouterView />
      <section v-if="currentVideo && route.path !== '/studio'" ref="player" class="player panel" aria-label="Reproductor">
        <p class="badge">Modo demostración: sin cobros reales</p>
        <div class="section-heading"><div><p class="eyebrow">EN ESCENA</p><h2>{{ currentVideo.titulo }}</h2><p>{{ currentVideo.pelicula }}</p></div><div class="actions"><button @click="large = !large">{{ large ? 'Vista normal' : 'Pantalla grande' }}</button><button @click="fullscreen">Pantalla completa</button></div></div>
        <p class="badge">Desde {{ plans[minimumPlan(currentVideo)].nombre }} · Popularidad {{ currentVideo.popularidad }}</p>
        <template v-if="allowed">
          <iframe v-if="currentVideo.proveedor === 'google-drive'" :key="currentVideo.fuente" :src="providers['google-drive'].playback(currentVideo.fuente)" :title="'Doblaje: ' + currentVideo.titulo" allow="fullscreen" allowfullscreen></iframe>
          <video v-else :key="currentVideo.fuente" :src="providers.html5.playback(currentVideo.fuente)" controls playsinline preload="metadata" @error="mediaError = true" @loadedmetadata="mediaError = false"></video>
          <p v-if="currentVideo.proveedor === 'html5' && mediaError" role="alert">No se pudo reproducir. Verificá que la URL sea un archivo de video accesible y compatible con tu navegador.</p>
          <p v-if="currentVideo.proveedor === 'google-drive'" class="muted">¿No carga? <a :href="providers['google-drive'].external(currentVideo.fuente)" target="_blank" rel="noopener noreferrer">Abrir en Google Drive ↗</a>. Los permisos se administran en Drive; el enlace no evita sus restricciones. No podemos detectar ni controlar el play dentro del iframe.</p>
        </template>
        <div v-else class="empty"><span class="empty-icon">▶</span><h3>{{ active ? 'Este doblaje no está incluido en tu plan' : access ? 'Tu suscripción venció' : 'Necesitás una suscripción' }}</h3><p>Disponible desde el plan {{ plans[minimumPlan(currentVideo)].nombre }}. No hay vistas gratuitas; un enlace compartido no concede acceso.</p><RouterLink class="button primary" to="/acceso">{{ active ? 'Cambiar de plan' : access ? 'Renovar suscripción demo' : 'Elegir suscripción' }}</RouterLink></div>
        <p class="muted">Doblaje preparado por el equipo. Podés volver a verlo mientras tu suscripción lo incluya.</p>
        <p v-if="fullscreenError" role="status">{{ fullscreenError }}</p>
      </section>
    </main>
    <footer class="shell"><span>{{ route.path === '/studio' ? 'Studio · En desarrollo: procesamiento local de IA.' : 'Catálogo · Google Drive activo; otros proveedores en desarrollo.' }}</span><button v-if="route.path !== '/studio' && !supabaseConfigured" @click="teamMode = !teamMode">{{ teamMode ? 'Volver a vista suscriptor' : 'Simular vista del equipo' }}</button><span v-if="teamMode && route.path !== '/studio'">Vista de prueba local.</span></footer>
  </div>
</template>
