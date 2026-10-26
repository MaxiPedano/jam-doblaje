create type public.app_role as enum ('admin', 'subscriber');
create type public.video_provider as enum ('google-drive', 'html5');
create type public.video_popularity as enum ('baja', 'media', 'alta');
create type public.subscription_plan as enum ('basico', 'estandar', 'premium');

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text,
  role public.app_role not null default 'subscriber',
  created_at timestamptz not null default now()
);

create table public.videos (
  id uuid primary key default gen_random_uuid(),
  title text not null check (char_length(title) between 1 and 160),
  movie text not null check (char_length(movie) between 1 and 160),
  genre text not null check (char_length(genre) between 1 and 60),
  popularity public.video_popularity not null default 'alta',
  thumbnail text,
  provider public.video_provider not null default 'google-drive',
  source text not null,
  published boolean not null default true,
  created_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  plan public.subscription_plan not null,
  starts_at timestamptz not null default now(),
  expires_at timestamptz not null,
  status text not null default 'active' check (status in ('active', 'cancelled', 'expired')),
  created_at timestamptz not null default now()
);

create table public.favorites (
  user_id uuid not null references public.profiles(id) on delete cascade,
  video_id uuid not null references public.videos(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, video_id)
);

create table public.watchlist (
  user_id uuid not null references public.profiles(id) on delete cascade,
  video_id uuid not null references public.videos(id) on delete cascade,
  position integer not null default 0,
  created_at timestamptz not null default now(),
  primary key (user_id, video_id)
);

create or replace function public.is_admin()
returns boolean language sql stable security definer set search_path = public
as $$ select exists (select 1 from public.profiles where id = auth.uid() and role = 'admin') $$;

create or replace function public.create_profile()
returns trigger language plpgsql security definer set search_path = public
as $$ begin insert into public.profiles (id, username) values (new.id, coalesce(new.raw_user_meta_data ->> 'username', split_part(new.email, '@', 1))); return new; end $$;

create trigger on_auth_user_created after insert on auth.users for each row execute function public.create_profile();

alter table public.profiles enable row level security;
alter table public.videos enable row level security;
alter table public.subscriptions enable row level security;
alter table public.favorites enable row level security;
alter table public.watchlist enable row level security;

create policy "Cada usuario ve su perfil" on public.profiles for select using (id = auth.uid() or public.is_admin());
create policy "El catálogo publicado es visible" on public.videos for select using (published = true or public.is_admin());
create policy "El equipo administra el catálogo" on public.videos for all using (public.is_admin()) with check (public.is_admin());
create policy "Cada usuario ve sus suscripciones" on public.subscriptions for select using (user_id = auth.uid() or public.is_admin());
create policy "El equipo administra suscripciones" on public.subscriptions for all using (public.is_admin()) with check (public.is_admin());
create policy "Cada usuario administra sus favoritos" on public.favorites for all using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "Cada usuario administra su lista" on public.watchlist for all using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Después del primer registro, promover manualmente la cuenta del equipo:
-- update public.profiles set role = 'admin' where id = 'UUID_DEL_USUARIO';
