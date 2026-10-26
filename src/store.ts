import { computed, ref, watch } from 'vue'
import initial from './data/catalog.json'
import { activate, canWatch, parseCatalog, remaining, validAccess, type Access, type Plan, type Video } from './domain'
import { supabase, supabaseConfigured, type Profile, type RemoteVideo } from './lib/supabase'

export const storageWarning = ref('')
function load(key: string): unknown {
  try { const raw = localStorage.getItem(`karaoke.${key}`); return raw ? JSON.parse(raw) : null }
  catch { storageWarning.value = 'No pudimos leer algunos datos locales. Podés volver a importar tu catálogo.'; return null }
}
function persist(key: string, value: unknown) {
  try { localStorage.setItem(`karaoke.${key}`, JSON.stringify(value)) }
  catch { storageWarning.value = 'No se pudieron guardar los cambios en este navegador. Exportá el catálogo para conservarlo.' }
}
let videos: Video[]
try { videos = parseCatalog(load('catalog') ?? initial).videos }
catch { videos = parseCatalog(initial).videos; storageWarning.value = 'El catálogo local no es válido. Se cargó el catálogo inicial.' }
export const catalog = ref(videos)
function ids(key: string): string[] {
  const value = load(key)
  return Array.isArray(value) ? [...new Set(value.filter((id): id is string => typeof id === 'string' && videos.some(v => v.id === id)))] : []
}
export const favorites = ref(ids('favorites'))
export const queue = ref(ids('queue'))
const storedAccess = load('access')
export const access = ref<Access | null>(validAccess(storedAccess) ? storedAccess : null)
export const teamMode = ref(false)
export const now = ref(Date.now())
export const authLoading = ref(supabaseConfigured)
export const user = ref<{ id: string; email?: string } | null>(null)
export const profile = ref<Profile | null>(null)
export const authError = ref('')
export const timeLeft = computed(() => remaining(access.value, now.value))
export const active = computed(() => timeLeft.value > 0)
export const selected = ref<string | null>(null)
export const currentVideo = computed(() => catalog.value.find(v => v.id === selected.value))
export const allowed = computed(() => !!currentVideo.value && canWatch(currentVideo.value, access.value, now.value))
export function refreshClock() { now.value = Date.now() }
export function buy(plan: Plan) {
  refreshClock()
  access.value = activate(plan, now.value)
  if (supabase && user.value) void saveRemoteSubscription(plan, access.value.expiresAt)
}
export function toggleFavorite(id: string) {
  const exists = favorites.value.includes(id)
  favorites.value = exists ? favorites.value.filter(i => i !== id) : [...favorites.value, id]
  if (supabase && user.value) void (exists
    ? supabase.from('favorites').delete().eq('user_id', user.value.id).eq('video_id', id)
    : supabase.from('favorites').insert({ user_id: user.value.id, video_id: id }))
}
export function enqueue(id: string) {
  if (queue.value.includes(id)) return
  queue.value.push(id)
  if (supabase && user.value) void supabase.from('watchlist').upsert({ user_id: user.value.id, video_id: id, position: queue.value.length - 1 })
}
export function saveVideo(video: Video) {
  const index = catalog.value.findIndex(v => v.id === video.id)
  if (index < 0) catalog.value.push(video)
  else catalog.value[index] = video
  if (supabase && profile.value?.role === 'admin') void saveRemoteVideo(video)
}
export async function removeVideo(id: string) {
  catalog.value = catalog.value.filter(item => item.id !== id)
  if (supabase && profile.value?.role === 'admin') {
    const { error } = await supabase.from('videos').delete().eq('id', id)
    if (error) authError.value = `No se pudo eliminar el doblaje: ${error.message}`
  }
}
export function replaceCatalog(next: Video[]) { catalog.value = next }
watch(catalog, value => {
  persist('catalog', { version: 1, videos: value })
  const exists = (id: string) => value.some(v => v.id === id)
  favorites.value = favorites.value.filter(exists)
  queue.value = queue.value.filter(exists)
  if (selected.value && !exists(selected.value)) selected.value = null
}, { deep: true, flush: 'sync' })
watch(favorites, value => persist('favorites', value), { deep: true, flush: 'sync' })
watch(queue, value => persist('queue', value), { deep: true, flush: 'sync' })
watch(access, value => persist('access', value), { deep: true, flush: 'sync' })

function fromRemote(video: RemoteVideo): Video {
  return { id: video.id, titulo: video.title, pelicula: video.movie, genero: video.genre,
    popularidad: video.popularity, miniatura: video.thumbnail ?? undefined,
    proveedor: video.provider, fuente: video.source }
}

function toRemote(video: Video) {
  return { id: video.id, title: video.titulo, movie: video.pelicula, genre: video.genero,
    popularity: video.popularidad, thumbnail: video.miniatura || null, provider: video.proveedor,
    source: video.fuente, published: true, created_by: user.value?.id ?? null }
}

async function saveRemoteVideo(video: Video) {
  if (!supabase) return
  const { error } = await supabase.from('videos').upsert(toRemote(video))
  if (error) authError.value = `No se pudo guardar el catálogo: ${error.message}`
}

async function saveRemoteSubscription(plan: Plan, expiresAt: number) {
  if (!supabase || !user.value) return
  const { error } = await supabase.from('subscriptions').insert({ user_id: user.value.id, plan, expires_at: new Date(expiresAt).toISOString() })
  if (error) authError.value = `No se pudo guardar la suscripción: ${error.message}`
}

async function loadRemoteState() {
  if (!supabase) return
  authLoading.value = true
  const [{ data: sessionData }, videosResult] = await Promise.all([
    supabase.auth.getSession(),
    supabase.from('videos').select('id,title,movie,genre,popularity,thumbnail,provider,source').eq('published', true).order('created_at', { ascending: false }),
  ])
  const sessionUser = sessionData.session?.user ?? null
  user.value = sessionUser ? { id: sessionUser.id, email: sessionUser.email } : null
  if (!videosResult.error && videosResult.data) catalog.value = videosResult.data.map(fromRemote)
  if (sessionUser) {
    const [{ data: profileData }, { data: subscriptionData }, { data: favoriteData }, { data: queueData }] = await Promise.all([
      supabase.from('profiles').select('id,username,role').eq('id', sessionUser.id).maybeSingle(),
      supabase.from('subscriptions').select('plan,expires_at,status').eq('user_id', sessionUser.id).eq('status', 'active').order('expires_at', { ascending: false }).limit(1).maybeSingle(),
      supabase.from('favorites').select('video_id').eq('user_id', sessionUser.id),
      supabase.from('watchlist').select('video_id').eq('user_id', sessionUser.id).order('position', { ascending: true }),
    ])
    profile.value = profileData as Profile | null
    const subscription = subscriptionData as { plan: Plan; expires_at: string } | null
    access.value = subscription ? { plan: subscription.plan, expiresAt: new Date(subscription.expires_at).getTime() } : null
    favorites.value = (favoriteData ?? []).map(row => row.video_id)
    queue.value = (queueData ?? []).map(row => row.video_id)
  } else {
    profile.value = null
  }
  authLoading.value = false
}

export async function signIn(email: string, password: string) {
  if (!supabase) throw new Error('Configurá Supabase antes de iniciar sesión.')
  authError.value = ''
  const { error } = await supabase.auth.signInWithPassword({ email, password })
  if (error) { authError.value = error.message; throw error }
  await loadRemoteState()
}

export async function signUp(email: string, password: string, username: string) {
  if (!supabase) throw new Error('Configurá Supabase antes de crear una cuenta.')
  authError.value = ''
  const { error } = await supabase.auth.signUp({ email, password, options: { data: { username } } })
  if (error) { authError.value = error.message; throw error }
  await loadRemoteState()
}

export async function signOut() {
  if (!supabase) return
  await supabase.auth.signOut()
  user.value = null; profile.value = null; access.value = null
}

if (supabase) {
  void loadRemoteState()
  supabase.auth.onAuthStateChange(() => { void loadRemoteState() })
}
