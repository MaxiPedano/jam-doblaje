<script setup lang="ts">
import { access, active, authError, authLoading, buy, now, refreshClock, signIn, signOut, signUp, user } from '../store'
import { plans, type Plan } from '../domain'
import { supabaseConfigured } from '../lib/supabase'
import { reactive, ref } from 'vue'
const form = reactive({ email: '', password: '', username: '' })
const register = ref(false)
const message = ref('')
const busy = ref(false)
async function purchase(plan: Plan) {
  if (access.value && active.value && !confirm('¿Reemplazar tu suscripción demo? El nuevo plan comienza ahora por un mes, sin prorrateo ni cobros.')) return
  message.value = ''; busy.value = true
  if (await buy(plan)) message.value = 'Plan demo guardado. No hay cobros reales.'
  busy.value = false
}
function expire() { if (access.value) { refreshClock(); access.value = { ...access.value, expiresAt: now.value - 1 } } }
function reset() { if (confirm('¿Reiniciar la suscripción demo? Tu catálogo, favoritos y cola se conservarán.')) access.value = null }
async function submitAuth() {
  message.value = ''; busy.value = true
  try {
    if (register.value) { await signUp(form.email, form.password, form.username); message.value = 'Cuenta creada. Revisá tu correo si Supabase solicita confirmación.' }
    else { await signIn(form.email, form.password); message.value = 'Sesión iniciada.' }
  } catch { /* El mensaje detallado se muestra desde authError. */ }
  finally { busy.value = false }
}
</script>
<template>
  <section class="page-intro"><p class="eyebrow">UN PLAN PARA CADA SELECCIÓN</p><h1>Tus doblajes, por suscripción.</h1><p>Elegí Básico, Estándar o Premium. Volvé a ver los doblajes incluidos las veces que quieras mientras tu suscripción esté activa.</p></section>
  <section v-if="supabaseConfigured" class="panel">
    <template v-if="user">
      <h2>Tu cuenta</h2><p>Sesión iniciada con <b>{{ user.email }}</b>.</p><button @click="signOut">Cerrar sesión</button>
    </template>
    <template v-else>
      <h2>{{ register ? 'Crear cuenta' : 'Iniciar sesión' }}</h2>
      <form class="form-grid" @submit.prevent="submitAuth">
        <label v-if="register">Nombre de usuario<input v-model="form.username" required minlength="3" maxlength="80" autocomplete="username"></label>
        <label>Email<input v-model="form.email" required type="email" autocomplete="email"></label>
        <label>Contraseña<input v-model="form.password" required type="password" minlength="12" autocomplete="current-password"></label>
        <div class="actions full"><button class="primary" :disabled="busy || authLoading" type="submit">{{ busy ? 'Procesando…' : register ? 'Crear cuenta' : 'Ingresar' }}</button><button type="button" @click="register = !register">{{ register ? 'Ya tengo cuenta' : 'Crear cuenta nueva' }}</button></div>
      </form>
      <p v-if="authError" class="notice" role="alert">{{ authError }}</p><p v-if="message" class="success" role="status">{{ message }}</p>
    </template>
  </section>
  <p v-else class="notice">Supabase todavía no está configurado. La cuenta y las suscripciones funcionan en modo demo local.</p>
  <p v-if="authError" class="notice" role="alert">{{ authError }}</p>
  <p class="notice">No hay reproducción gratuita. Los planes son acumulativos y tienen una cuota mensual fija, sin cargos por reproducción. Los precios aún están a definir: estas activaciones son simuladas.</p>
  <div class="plans subscription-plans">
    <article v-for="(plan, key) in plans" :key="key" class="panel" :class="{ 'current-plan': active && access?.plan === key }">
      <span class="badge">{{ key === 'premium' ? 'TODO EL CATÁLOGO' : key === 'estandar' ? 'MÁS DOBLAJES' : 'TU PRIMERA SELECCIÓN' }}</span>
      <h2>{{ plan.nombre }}</h2><p class="plan-number">A definir <small>/ mes</small></p><p>{{ plan.descripcion }}</p>
      <p class="muted">Un mes calendario desde la activación. Sin renovación automática en la demo.</p>
       <button class="primary" :disabled="busy || authLoading || (supabaseConfigured && !user)" @click="purchase(key)">{{ active && access?.plan === key ? 'Renovar demo' : 'Simular suscripción' }} {{ plan.nombre }}</button>
    </article>
  </div>
  <section class="panel"><h2>Tu suscripción</h2>
    <template v-if="access"><p>Plan: <b>{{ plans[access.plan].nombre }}</b> · {{ active ? 'Activo' : 'Vencido' }}</p><p>{{ active ? 'Vence' : 'Venció' }}: <b>{{ new Date(access.expiresAt).toLocaleString('es-AR') }}</b></p><p v-if="!active" role="status">Tu suscripción venció. El reproductor se desmontó. Elegí un plan para renovar la demo.</p><RouterLink v-else class="button primary" to="/">Explorar mis doblajes disponibles</RouterLink></template>
    <p v-else>No tenés una suscripción activa. Elegí un plan para probar el acceso.</p>
     <div v-if="!supabaseConfigured" class="actions controls"><button :disabled="!access" @click="expire">Simular vencimiento</button><button @click="reset">Reiniciar demo</button></div>
     <p v-else class="muted">El plan demo se guarda en Supabase y el servidor calcula el vencimiento. No hay cobros reales.</p>
  </section>
  <section class="panel"><h2>¿Cómo se asignan los videos?</h2><p>El equipo carga el doblaje terminado y define su popularidad: baja → Básico, media → Estándar, alta → Premium. Estándar también incluye Básico; Premium incluye todos. La popularidad es editorial, no un contador automático de reproducciones.</p><p>Compartir un enlace no habilita el video: el destinatario necesita una suscripción activa que lo incluya.</p></section>
  <p class="notice">Google Drive funciona como proveedor activo. El archivo debe tener permisos de visualización en Drive; para proteger completamente el contenido y generar enlaces temporales migraremos luego a Cloudflare Stream. HTML5 y el procesamiento IA permanecen en desarrollo.</p>
</template>
