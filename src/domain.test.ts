import { describe, expect, it } from 'vitest'
import { activate, canWatch, driveId, parseCatalog, providers, remaining, searchVideos, validAccess, type Plan, type Popularity, type Video } from './domain'

// Identificadores sintéticos: no se intenta acceder a ningún video externo.
const song: Video = { id: 'prueba', titulo: 'Última escena', pelicula: 'Película ficticia', genero: 'Drama', popularidad: 'alta', proveedor: 'google-drive', fuente: 'ID_FICTICIO_12345' }
describe('catálogo y búsqueda', () => {
  it('busca por escena o película, sin distinguir acentos ni mayúsculas, y filtra género', () => {
    expect(searchVideos([song], ' ULTIMA ', '')).toEqual([song])
    expect(searchVideos([song], 'pelicula', 'Drama')).toEqual([song])
    expect(searchVideos([song], 'pelicula', 'Comedia')).toEqual([])
    expect(searchVideos([song], 'inexistente', '')).toEqual([])
  })
  it('exporta y reimporta datos equivalentes', () => {
    const exported = JSON.stringify({ version: 1, videos: [song] })
    expect(parseCatalog(JSON.parse(exported)).videos).toEqual([song])
  })
  it('recupera el campo heredado sin perder el catálogo anterior', () => {
    const { pelicula, popularidad, ...legacy } = song
    expect(parseCatalog({ version: 1, videos: [{ ...legacy, artista: pelicula }] }).videos).toEqual([song])
  })
  it('rechaza formatos, duplicados y fuentes peligrosas', () => {
    for (const input of [null, [], { version: 2, videos: [] }, { version: 1, videos: [song, song] },
      { version: 1, videos: [{ ...song, titulo: '' }] },
      { version: 1, videos: [{ ...song, popularidad: 'gratis' }] },
      { version: 1, videos: [{ ...song, proveedor: 'youtube' }] },
      { version: 1, videos: [{ ...song, miniatura: 'data:image/png;base64,abc' }] },
      { version: 1, videos: [{ ...song, proveedor: 'html5', fuente: 'javascript:alert(1)' }] },
      { version: 1, videos: [{ ...song, proveedor: 'html5', fuente: 'https://usuario:clave@example.com/video' }] },
    ]) expect(() => parseCatalog(input)).toThrow()
  })
})
describe('proveedores', () => {
  it('usa vista previa de Drive, no enlaces directos inventados', () => {
    expect(driveId('https://drive.google.com/file/d/ID_FICTICIO_12345/view?usp=sharing')).toBe(song.fuente)
    expect(driveId('https://drive.google.com/open?id=ID_FICTICIO_12345')).toBe(song.fuente)
    expect(providers['google-drive'].playback(song.fuente)).toBe('https://drive.google.com/file/d/ID_FICTICIO_12345/preview')
  })
  it('rechaza hosts engañosos, carpetas y protocolos inesperados', () => {
    for (const url of ['http://drive.google.com/file/d/ID_FICTICIO_12345/view', 'https://drive.google.com.evil.test/file/d/ID_FICTICIO_12345/view', 'https://drive.google.com/drive/folders/ID_FICTICIO_12345', 'file:///video.mp4']) expect(() => driveId(url)).toThrow()
  })
})
describe('suscripciones', () => {
  it('calcula vencimiento absoluto y sobrevive serialización', () => {
    const now = Date.now()
    const started = activate('basico', now)
    const reloaded = JSON.parse(JSON.stringify(started))
    expect(remaining(reloaded, now + 10 * 60_000)).toBe(started.expiresAt - now - 10 * 60_000)
    expect(remaining(reloaded, started.expiresAt)).toBe(0)
  })
  it('limita el mes al último día disponible sin saltar a marzo', () => {
    const jan31 = new Date(2026, 0, 31, 12).getTime()
    const end = activate('premium', jan31).expiresAt
    expect(new Date(end).getMonth()).toBe(1)
    expect(new Date(end).getDate()).toBe(28)
  })
  it('descarta datos locales inválidos', () => {
    expect(validAccess(activate('basico', Date.now()))).toBe(true)
    expect(validAccess({ plan: 'pase', expiresAt: Date.now() })).toBe(false)
    expect(validAccess({ plan: 'premium', expiresAt: 'mañana' })).toBe(false)
    expect(validAccess({ plan: 'premium', expiresAt: null })).toBe(false)
  })
  it('comprueba las nueve combinaciones de plan y popularidad, sin acceso anónimo ni vencido', () => {
    const now = Date.now()
    const levels: Plan[] = ['basico', 'estandar', 'premium']
    const popularities: Popularity[] = ['baja', 'media', 'alta']
    levels.forEach((plan, i) => popularities.forEach((popularidad, j) => {
      const video = { ...song, popularidad }
      expect(canWatch(video, activate(plan, now), now)).toBe(i >= j)
      expect(canWatch(video, null, now)).toBe(false)
      expect(canWatch(video, { plan, expiresAt: now }, now)).toBe(false)
    }))
  })
})
