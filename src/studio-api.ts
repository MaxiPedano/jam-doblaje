export interface StudioStatus { configured: boolean; modelReady: boolean; speakerReady: boolean; maxUploadBytes: number; maxSeconds: number; mode: string; model: string }
export interface StudioUser { id: number; username: string; role: 'admin' | 'subscriber' }
export type JobStatus = 'uploading' | 'queued' | 'processing' | 'voices' | 'ready' | 'failed'
export type JobMode = 'voces' | 'dialogo' | 'voz'
export interface StudioJob { id: string; name: string; status: JobStatus; progress: number; message: string; created: number; seconds: number | null; modo: JobMode; ranges: string }
export interface UploadOptions { modo: JobMode; ranges: string }
export interface SpeakerVoice { stream: number; energy_db: number; share: number; exclusive_pct: number; pitch_hz: number; pitch_strength: number }
export interface SpeakersInfo { model: string; n_speakers: number; n_voices: number; voices: SpeakerVoice[]; both_strong_pct: number; warnings: string[]; strategy: string }
export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}
function errorMessage(value: unknown): string {
  const detail = (value as { detail?: unknown })?.detail
  return typeof detail === 'string' ? detail : 'Revisá los datos ingresados o consultá el estado del servidor.'
}
export async function studioApi<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api/studio${path}`, { method, credentials: 'same-origin', signal: AbortSignal.timeout(15000),
      headers: { 'X-Doblaje-Request': 'studio', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined })
  } catch { throw new ApiError('No se pudo conectar con el backend local. Iniciá el servidor y volvé a intentar.', 0) }
  if (response.status === 204) return undefined as T
  const value = await response.json().catch(() => null)
  if (!response.ok || value === null) throw new ApiError(value ? errorMessage(value) : 'El backend local no está disponible.', response.status)
  return value as T
}
export function uploadVideo(file: File, progress: (percent: number) => void, options?: UploadOptions): { request: XMLHttpRequest; done: Promise<StudioJob> } {
  const params = new URLSearchParams()
  params.set('modo', options?.modo ?? 'voces')
  const ranges = (options?.ranges ?? '').trim()
  if (params.get('modo') === 'dialogo' && ranges) params.set('ranges', ranges)
  const request = new XMLHttpRequest()
  const done = new Promise<StudioJob>((resolve, reject) => {
    request.open('POST', `/api/studio/jobs?${params.toString()}`)
    request.timeout = 660000
    request.setRequestHeader('X-Doblaje-Request', 'studio')
    request.setRequestHeader('X-File-Name', encodeURIComponent(file.name))
    request.setRequestHeader('Content-Type', 'application/octet-stream')
    request.upload.onprogress = event => { if (event.lengthComputable) progress(Math.round(event.loaded / event.total * 100)) }
    request.onload = () => {
      let data
      try { data = JSON.parse(request.responseText) } catch { reject(new ApiError('El servidor no devolvió una respuesta válida.', request.status)); return }
      if (request.status >= 200 && request.status < 300) resolve(data)
      else reject(new ApiError(errorMessage(data), request.status))
    }
    request.onerror = () => reject(new ApiError('Se interrumpió la conexión durante la carga.', 0))
    request.ontimeout = () => reject(new ApiError('La carga superó el tiempo máximo.', 0))
    request.onabort = () => reject(new ApiError('Carga cancelada.', 0))
    request.send(file)
  })
  return { request, done }
}
export function remixJob(id: string, modo: 'voces' | 'dialogo', ranges: string): Promise<{ accepted: boolean }> {
  return studioApi<{ accepted: boolean }>(`/jobs/${id}/remix`, 'POST', { modo, ranges })
}
export function removeVoice(id: string, target: string): Promise<{ accepted: boolean }> {
  return studioApi<{ accepted: boolean }>(`/jobs/${id}/remove-voice`, 'POST', { target })
}
export function getSpeakers(id: string): Promise<SpeakersInfo> {
  return studioApi<SpeakersInfo>(`/jobs/${id}/speakers`)
}
export function sampleMedia(id: string, which: number): string {
  return `/api/studio/jobs/${id}/media/sample?which=${which}`
}
