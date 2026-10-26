<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { access, catalog, enqueue, favorites, moveQueue, now, queue, removeFromQueue, teamMode, toggleFavorite } from '../store'
import { canWatch, minimumPlan, plans, searchVideos, type Plan } from '../domain'
const router = useRouter()
const props = defineProps<{ personal?: boolean }>()
const query = ref('')
const genre = ref('')
const onlyIncluded = ref(false)
const genres = computed(() => [...new Set(catalog.value.map(v => v.genero))].sort())
const results = computed(() => searchVideos(props.personal ? catalog.value.filter(v => favorites.value.includes(v.id)) : catalog.value, query.value, genre.value).filter(v => !onlyIncluded.value || canWatch(v, access.value, now.value)))
const queued = computed(() => queue.value.map(id => catalog.value.find(v => v.id === id)).filter(v => !!v))
const examples: { titulo: string; pelicula: string; genero: string; plan: Plan }[] = [
  { titulo: 'La última despedida', pelicula: 'El tren de las seis', genero: 'Drama', plan: 'basico' },
  { titulo: 'Un plan muy improvisado', pelicula: 'Vecinos de otro planeta', genero: 'Comedia', plan: 'estandar' },
  { titulo: 'Cuenta regresiva', pelicula: 'Misión en la niebla', genero: 'Acción', plan: 'premium' },
]
function move(index: number, direction: number) {
  void moveQueue(index, direction)
}
function play(id: string) { router.push(`/doblaje/${encodeURIComponent(id)}`) }
async function next() { const id = queue.value[0]; if (id) { const v = catalog.value.find(v => v.id === id); if (v && canWatch(v, access.value, Date.now()) && await removeFromQueue(id)) play(id) } }
</script>
<template>
  <section class="hero"><div><p class="eyebrow">HISTORIAS CON OTRA VOZ</p><h1>{{ personal ? 'Tus doblajes.' : 'Grandes escenas.' }}<br><span>{{ personal ? 'Cuando vos quieras.' : 'Nuevas interpretaciones.' }}</span></h1><p>{{ personal ? 'Tus favoritos y tu lista para volver a ver, en un solo lugar.' : 'Doblajes preparados por nuestro equipo. Elegí tu suscripción y disfrutá de los videos incluidos las veces que quieras.' }}</p><RouterLink class="button primary" to="/acceso">Conocer los planes</RouterLink></div><div class="hero-art" aria-hidden="true"><span>▶</span><small>OTRA FORMA DE VER CINE</small></div></section>
   <section v-if="personal" class="panel queue"><div class="section-heading"><h2>Mi lista <span class="count">{{ queued.length }}</span></h2><button class="primary" :disabled="!queued.length" @click="next">Ver el siguiente</button></div><p v-if="!queued.length" class="muted">Agregá doblajes desde el catálogo para verlos después.</p><ol><li v-for="(video, index) in queued" :key="video.id"><span><b>{{ video.titulo }}</b> · {{ video.pelicula }} · Desde {{ plans[minimumPlan(video)].nombre }}</span><div class="actions"><button :disabled="index === 0" :aria-label="'Subir ' + video.titulo" @click="move(index, -1)">↑</button><button :disabled="index === queued.length - 1" :aria-label="'Bajar ' + video.titulo" @click="move(index, 1)">↓</button><button @click="play(video.id)">Ver doblaje</button><button :aria-label="'Quitar ' + video.titulo + ' de la lista'" @click="removeFromQueue(video.id)">Quitar</button></div></li></ol></section>
  <div class="section-heading"><h2>{{ personal ? 'Tus doblajes favoritos' : 'Explorá los doblajes' }} <span class="count">{{ results.length }}</span></h2><span class="muted">Sin reproducción gratuita</span></div>
  <div class="search-row"><label class="search"><span>Buscar doblaje o película</span><input v-model="query" type="search" placeholder="¿Qué te gustaría ver?"></label><label>Género<select v-model="genre"><option value="">Todos los géneros</option><option v-for="g in genres" :key="g">{{ g }}</option></select></label></div>
  <label class="checkbox-label"><input v-model="onlyIncluded" type="checkbox">Solo disponibles en mi suscripción activa</label>
  <div v-if="results.length" class="cards"><article v-for="video in results" :key="video.id" class="song-card"><div class="cover"><span aria-hidden="true">▶</span><img v-if="video.miniatura" :src="video.miniatura" alt="" loading="lazy" referrerpolicy="no-referrer" @error="($event.target as HTMLImageElement).style.display = 'none'"><span class="genre">{{ video.genero }} · {{ plans[minimumPlan(video)].nombre }}</span></div><div class="song-body"><h3>{{ video.titulo }}</h3><p>{{ video.pelicula }}</p><p class="badge">{{ canWatch(video, access, now) ? 'Incluido en tu suscripción' : 'Requiere ' + plans[minimumPlan(video)].nombre + ' o superior' }} · Popularidad {{ video.popularidad }}</p><div class="actions"><button class="primary" @click="play(video.id)">{{ canWatch(video, access, now) ? '▶ Ver doblaje' : 'Ver requisitos' }}</button><button :aria-label="(favorites.includes(video.id) ? 'Quitar de favoritos: ' : 'Agregar a favoritos: ') + video.titulo" :aria-pressed="favorites.includes(video.id)" @click="toggleFavorite(video.id)">{{ favorites.includes(video.id) ? '♥' : '♡' }}</button><button :disabled="queue.includes(video.id)" @click="enqueue(video.id)">{{ queue.includes(video.id) ? 'En lista ✓' : '+ Lista' }}</button></div></div></article></div>
  <div v-else class="empty panel"><span class="empty-icon">▶</span><h3>{{ !catalog.length ? 'Los primeros doblajes están por llegar' : 'No encontramos doblajes' }}</h3><p>{{ !catalog.length ? 'El equipo está preparando el catálogo. Conocé los planes mientras tanto.' : 'Revisá la búsqueda, los filtros y tu suscripción activa.' }}</p><RouterLink v-if="teamMode && !catalog.length" class="button primary" to="/configuracion">+ Cargar el primer doblaje</RouterLink></div>
  <section v-if="!catalog.length && !personal" class="examples"><div class="section-heading"><h2>Así se verá el catálogo</h2><span class="badge">EJEMPLOS FICTICIOS · SIN VIDEO</span></div><div class="cards"><article v-for="(example, i) in examples" :key="example.titulo" class="song-card fictional"><div class="cover" :class="'cover-' + i"><span aria-hidden="true">▶</span><span class="genre">{{ example.genero }} · {{ plans[example.plan].nombre }}</span></div><div class="song-body"><h3>{{ example.titulo }}</h3><p>{{ example.pelicula }}</p><small>Doblaje y película ficticios · No reproducible</small></div></article></div></section>
</template>
