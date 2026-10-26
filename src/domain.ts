export type Provider = 'google-drive' | 'html5'
export type Plan = 'basico' | 'estandar' | 'premium'
export type Popularity = 'baja' | 'media' | 'alta'
export const plans: Record<Plan, { nombre: string; rank: number; descripcion: string }> = {
  basico: { nombre: 'Básico', rank: 1, descripcion: 'Doblajes de popularidad baja.' },
  estandar: { nombre: 'Estándar', rank: 2, descripcion: 'Popularidad media y todo el catálogo Básico.' },
  premium: { nombre: 'Premium', rank: 3, descripcion: 'Los más populares y todo el catálogo de los otros planes.' },
}
export const popularityPlans: Record<Popularity, Plan> = { baja: 'basico', media: 'estandar', alta: 'premium' }
export function minimumPlan(video: Video): Plan { return popularityPlans[video.popularidad] }
export interface Video {
  id: string
  titulo: string
  pelicula: string
  genero: string
  popularidad: Popularity
  miniatura?: string
  proveedor: Provider
  fuente: string
}
export interface Catalog { version: 1; videos: Video[] }
export interface Access {
  plan: Plan
  expiresAt: number
}
export function httpsUrl(value: string): string {
  const url = new URL(value)
  if (url.protocol !== 'https:' || url.username || url.password) throw new Error('Usá una URL HTTPS sin credenciales.')
  return url.href
}
export function driveId(value: string): string {
  if (/^[\w-]{10,200}$/.test(value)) return value
  const url = new URL(httpsUrl(value))
  if (url.hostname !== 'drive.google.com' || url.port) throw new Error('El enlace debe pertenecer a drive.google.com.')
  const id = url.pathname.match(/^\/file\/d\/([\w-]+)(?:\/(?:view|preview))?\/?$/)?.[1]
    ?? (['/open', '/uc'].includes(url.pathname) ? url.searchParams.get('id') : null)
  if (!id || !/^[\w-]{10,200}$/.test(id)) throw new Error('Pegá un enlace de archivo de Drive o su identificador válido.')
  return id
}
export const providers = {
  'google-drive': {
    normalize: driveId,
    playback: (source: string) => `https://drive.google.com/file/d/${driveId(source)}/preview`,
    external: (source: string) => `https://drive.google.com/file/d/${driveId(source)}/view`,
  },
  html5: { normalize: httpsUrl, playback: httpsUrl, external: httpsUrl },
}
function text(value: unknown, field: string, max = 160): string {
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new Error(`${field}: texto obligatorio, máximo ${max} caracteres.`)
  return value.trim()
}
export function validateVideo(input: unknown): Video {
  if (!input || typeof input !== 'object') throw new Error('Escena inválida.')
  const v = input as Record<string, unknown>
  if (v.proveedor !== 'google-drive' && v.proveedor !== 'html5') throw new Error('Proveedor no admitido.')
  // Los catálogos anteriores quedan en el nivel más restrictivo hasta revisión del equipo.
  const popularidad = v.popularidad === undefined ? 'alta' : v.popularidad
  if (popularidad !== 'baja' && popularidad !== 'media' && popularidad !== 'alta') throw new Error('Popularidad inválida: usá baja, media o alta.')
  const id = text(v.id, 'ID', 100)
  if (!/^[a-zA-Z0-9_-]+$/.test(id)) throw new Error('ID: solo letras, números, guion y guion bajo.')
  return {
    id, titulo: text(v.titulo, 'Título de la escena'), pelicula: text(v.pelicula ?? v.artista, 'Película'), genero: text(v.genero, 'Género', 60),
    popularidad, proveedor: v.proveedor, fuente: providers[v.proveedor].normalize(text(v.fuente, 'Enlace', 2048)),
    ...(v.miniatura !== undefined && v.miniatura !== '' ? { miniatura: httpsUrl(text(v.miniatura, 'Miniatura', 2048)) } : {}),
  }
}
export function parseCatalog(input: unknown): Catalog {
  const c = input as Partial<Catalog> | null
  if (!c || c.version !== 1 || !Array.isArray(c.videos) || c.videos.length > 5000) throw new Error('Se espera { "version": 1, "videos": [...] }, con hasta 5000 escenas.')
  const videos = c.videos.map(validateVideo)
  if (new Set(videos.map(v => v.id)).size !== videos.length) throw new Error('Hay identificadores duplicados.')
  return { version: 1, videos }
}
const normalized = (s: string) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
export function searchVideos(videos: Video[], query: string, genre: string): Video[] {
  return videos.filter(v => (!genre || v.genero === genre) && normalized(`${v.titulo} ${v.pelicula}`).includes(normalized(query.trim())))
}
export function remaining(access: Access | null, now: number): number {
  return access?.expiresAt ? Math.max(0, access.expiresAt - now) : 0
}
export function activate(plan: Plan, now: number): Access {
  const date = new Date(now)
    const day = date.getDate()
    date.setDate(1)
    date.setMonth(date.getMonth() + 1)
    const lastDay = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate()
    date.setDate(Math.min(day, lastDay))
  return { plan, expiresAt: date.getTime() }
}
export function validAccess(value: unknown): value is Access {
  const a = value as Access | null
  return !!a && ['basico', 'estandar', 'premium'].includes(a.plan)
    && Number.isFinite(a.expiresAt) && a.expiresAt > 0 && a.expiresAt < 8.64e15
}
export function canWatch(video: Video, access: Access | null, now: number): boolean {
  return validAccess(access) && remaining(access, now) > 0 && plans[access.plan].rank >= plans[minimumPlan(video)].rank
}
