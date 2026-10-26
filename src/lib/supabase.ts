import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const key = import.meta.env.VITE_SUPABASE_ANON_KEY

export const supabaseConfigured = typeof url === 'string' && typeof key === 'string' && url.length > 0 && key.length > 0
export const supabase: SupabaseClient | null = supabaseConfigured ? createClient(url as string, key as string) : null

export interface Profile {
  id: string
  username: string | null
  role: 'admin' | 'subscriber'
}

export interface RemoteVideo {
  id: string
  title: string
  movie: string
  genre: string
  popularity: 'baja' | 'media' | 'alta'
  thumbnail: string | null
  provider: 'google-drive' | 'html5'
  source: string
}
