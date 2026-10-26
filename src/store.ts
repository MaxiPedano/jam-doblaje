import { computed, ref, watch } from 'vue'
import initial from './data/catalog.json'
import { activate, canWatch, parseCatalog, remaining, validAccess, type Access, type Plan, type Video } from './domain'
import { supabase, supabaseConfigured, type Profile, type RemoteVideo } from './lib/supabase'

export const storageWarning = ref('')
export const authError = ref('')

function load(key: string): unknown {
  try {
    const raw = localStorage.getItem(`karaoke.${key}`)
    return raw ? JSON.parse(raw) : null
  } catch {
    storageWarning.value = 'No pudimos leer algunos datos locales. Podés volver a importar tu catálogo.'
    return null
  }
}

function persist(key: string, value: unknown) {
  try { localStorage.setItem(`karaoke.${key}`, JSON.stringify(value)) }
  catch { storageWarning.value = 'No se pudieron guardar los cambios en este navegador. Exportá el catálogo para conservarlo.' }
}

function localCatalog(): Video[] {
  try { return parseCatalog(load('catalog') ?? initial).videos }
  catch {
    storageWarning.value = 'El catálogo local no es válido. Se cargó el catálogo inicial.'
    return parseCatalog(initial).videos
  }
}

let videos = supabaseConfigured ? [] : localCatalog()
export const catalog = ref<Video[]>(videos)

function localIds(key: string): string[] {
  const value = load(key)
  return Array.isArray(value)
    ? [...new Set(value.filter((id): id is string => typeof id === 'string' && videos.some(v => v.id === id)))]
    : []
}

export const favorites = ref<string[]>(supabaseConfigured ? [] : localIds('favorites'))
export const queue = ref<string[]>(supabaseConfigured ? [] : localIds('queue'))
const storedAccess = supabaseConfigured ? null : load('access')
export const access = ref<Access | null>(validAccess(storedAccess) ? storedAccess : null)
export const teamMode = ref(false)
export const now = ref(Date.now())
export const authLoading = ref(supabaseConfigured)
export const user = ref<{ id: string; email?: string } | null>(null)
export const profile = ref<Profile | null>(null)
export const timeLeft = computed(() => remaining(access.value, now.value))
export const active = computed(() => timeLeft.value > 0)
export const selected = ref<string | null>(null)
export const currentVideo = computed(() => catalog.value.find(v => v.id === selected.value))
export const allowed = computed(() => !!currentVideo.value && canWatch(currentVideo.value, access.value, now.value))

export function refreshClock() { now.value = Date.now() }

function setError(prefix: string, error: { message: string } | null) {
  if (error) authError.value = `${prefix}: ${error.message}`
}

function replaceLocalVideo(video: Video) {
  const index = catalog.value.findIndex(item => item.id === video.id)
  if (index < 0) catalog.value.push(video)
  else catalog.value[index] = video
}

function clearPersonalState() {
  favorites.value = []
  queue.value = []
  access.value = null
  profile.value = null
  teamMode.value = false
}

export async function activateDemoSubscription(plan: Plan): Promise<boolean> {
  refreshClock()
  if (supabaseConfigured && !user.value) {
    authError.value = 'Iniciá sesión para activar un plan demo.'
    return false
  }
  if (!supabase) {
    access.value = activate(plan, now.value)
    return true
  }
  const { data, error } = await supabase.rpc('activate_demo_subscription', { selected_plan: plan })
  if (error) { setError('No se pudo guardar la suscripción', error); return false }
  const row = Array.isArray(data) ? data[0] : data
  if (!row?.plan || !row?.expires_at) {
    authError.value = 'No se pudo leer la suscripción confirmada por el servidor.'
    return false
  }
  access.value = { plan: row.plan as Plan, expiresAt: new Date(row.expires_at).getTime() }
  return true
}

// Alias conservado para el modo local y los tests existentes.
export function buy(plan: Plan) { return activateDemoSubscription(plan) }

export async function toggleFavorite(id: string): Promise<boolean> {
  const exists = favorites.value.includes(id)
  const next = exists ? favorites.value.filter(item => item !== id) : [...favorites.value, id]
  if (!supabase || !user.value) {
    favorites.value = next
    return true
  }
  const result = exists
    ? await supabase.from('favorites').delete().eq('user_id', user.value.id).eq('video_id', id)
    : await supabase.from('favorites').insert({ user_id: user.value.id, video_id: id })
  if (result.error) { setError('No se pudo actualizar favoritos', result.error); return false }
  favorites.value = next
  return true
}

export async function setWatchlist(next: string[]): Promise<boolean> {
  const normalized = [...new Set(next)].filter(id => catalog.value.some(video => video.id === id))
  if (!supabase || !user.value) {
    queue.value = normalized
    return true
  }
  const { error } = await supabase.rpc('set_watchlist', { video_ids: normalized })
  if (error) { setError('No se pudo guardar la lista', error); return false }
  queue.value = normalized
  return true
}

export function enqueue(id: string) {
  if (queue.value.includes(id)) return Promise.resolve(true)
  return setWatchlist([...queue.value, id])
}

export function removeFromQueue(id: string) {
  return setWatchlist(queue.value.filter(item => item !== id))
}

export function moveQueue(index: number, direction: number) {
  const other = index + direction
  if (other < 0 || other >= queue.value.length) return Promise.resolve(false)
  const next = [...queue.value]
  ;[next[index], next[other]] = [next[other]!, next[index]!]
  return setWatchlist(next)
}

export async function saveVideo(video: Video): Promise<boolean> {
  if (!supabase) {
    replaceLocalVideo(video)
    return true
  }
  if (profile.value?.role !== 'admin') {
    authError.value = 'Solo una cuenta administradora puede modificar el catálogo.'
    return false
  }
  const { error } = await supabase.from('videos').upsert({
    id: video.id, title: video.titulo, movie: video.pelicula, genre: video.genero,
    popularity: video.popularidad, thumbnail: video.miniatura || null, provider: video.proveedor,
    source: video.fuente, published: true, created_by: user.value?.id,
  })
  if (error) { setError('No se pudo guardar el doblaje', error); return false }
  replaceLocalVideo(video)
  return true
}

export async function removeVideo(id: string): Promise<boolean> {
  if (!supabase) {
    catalog.value = catalog.value.filter(item => item.id !== id)
    return true
  }
  if (profile.value?.role !== 'admin') {
    authError.value = 'Solo una cuenta administradora puede modificar el catálogo.'
    return false
  }
  const { error } = await supabase.from('videos').delete().eq('id', id)
  if (error) { setError('No se pudo eliminar el doblaje', error); return false }
  catalog.value = catalog.value.filter(item => item.id !== id)
  return true
}

export function replaceCatalog(next: Video[]) { catalog.value = next }

watch(catalog, value => {
  if (supabaseConfigured) return
  persist('catalog', { version: 1, videos: value })
  const exists = (id: string) => value.some(v => v.id === id)
  favorites.value = favorites.value.filter(exists)
  queue.value = queue.value.filter(exists)
  if (selected.value && !exists(selected.value)) selected.value = null
}, { deep: true, flush: 'sync' })
watch(favorites, value => { if (!supabaseConfigured) persist('favorites', value) }, { deep: true, flush: 'sync' })
watch(queue, value => { if (!supabaseConfigured) persist('queue', value) }, { deep: true, flush: 'sync' })
watch(access, value => { if (!supabaseConfigured) persist('access', value) }, { deep: true, flush: 'sync' })

function fromRemote(video: RemoteVideo): Video {
  return { id: video.id, titulo: video.title, pelicula: video.movie, genero: video.genre,
    popularidad: video.popularity, miniatura: video.thumbnail ?? undefined,
    proveedor: video.provider, fuente: video.source }
}

let loadSequence = 0
async function loadRemoteState() {
  if (!supabase) return
  const sequence = ++loadSequence
  authLoading.value = true
  const [{ data: sessionData }, videosResult] = await Promise.all([
    supabase.auth.getSession(),
    supabase.from('videos').select('id,title,movie,genre,popularity,thumbnail,provider,source').eq('published', true).order('created_at', { ascending: false }),
  ])
  if (sequence !== loadSequence) return
  const sessionUser = sessionData.session?.user ?? null
  user.value = sessionUser ? { id: sessionUser.id, email: sessionUser.email } : null
  if (videosResult.error) setError('No se pudo cargar el catálogo', videosResult.error)
  else {
    const preserved = selected.value
    catalog.value = (videosResult.data ?? []).map(fromRemote)
    if (preserved && catalog.value.some(video => video.id === preserved)) selected.value = preserved
  }
  if (!sessionUser) {
    clearPersonalState()
    authLoading.value = false
    return
  }
  const [{ data: profileData, error: profileError }, { data: subscriptionData, error: subscriptionError }, { data: favoriteData, error: favoriteError }, { data: queueData, error: queueError }] = await Promise.all([
    supabase.from('profiles').select('id,username,role').eq('id', sessionUser.id).maybeSingle(),
    supabase.from('subscriptions').select('plan,expires_at,status').eq('user_id', sessionUser.id).eq('status', 'active').order('expires_at', { ascending: false }).limit(1).maybeSingle(),
    supabase.from('favorites').select('video_id').eq('user_id', sessionUser.id),
    supabase.from('watchlist').select('video_id').eq('user_id', sessionUser.id).order('position', { ascending: true }),
  ])
  if (sequence !== loadSequence) return
  if (profileError) setError('No se pudo cargar el perfil', profileError)
  if (subscriptionError) setError('No se pudo cargar la suscripción', subscriptionError)
  if (favoriteError) setError('No se pudieron cargar los favoritos', favoriteError)
  if (queueError) setError('No se pudo cargar la lista', queueError)
  profile.value = profileData as Profile | null
  const subscription = subscriptionData as { plan: Plan; expires_at: string } | null
  access.value = subscription ? { plan: subscription.plan, expiresAt: new Date(subscription.expires_at).getTime() } : null
  favorites.value = (favoriteData ?? []).map(row => row.video_id)
  queue.value = (queueData ?? []).map(row => row.video_id)
  authLoading.value = false
}

export async function signIn(email: string, password: string) {
  if (!supabase) throw new Error('Configurá Supabase antes de iniciar sesión.')
  authError.value = ''
  const { error } = await supabase.auth.signInWithPassword({ email, password })
  if (error) { setError('No se pudo iniciar sesión', error); throw error }
  await loadRemoteState()
}

export async function signUp(email: string, password: string, username: string) {
  if (!supabase) throw new Error('Configurá Supabase antes de crear una cuenta.')
  authError.value = ''
  const { error } = await supabase.auth.signUp({ email, password, options: { data: { username } } })
  if (error) { setError('No se pudo crear la cuenta', error); throw error }
  await loadRemoteState()
}

export async function signOut() {
  if (!supabase) return
  const { error } = await supabase.auth.signOut()
  if (error) { setError('No se pudo cerrar sesión', error); return }
  user.value = null
  clearPersonalState()
  authError.value = ''
  await loadRemoteState()
}

if (supabase) {
  void loadRemoteState()
  supabase.auth.onAuthStateChange(() => {
    window.setTimeout(() => { void loadRemoteState() }, 0)
  })
}
