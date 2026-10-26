-- Esquema de referencia ya aplicado en el proyecto de Supabase.
-- No lo ejecutes como una migración sobre una base existente sin revisarlo.

create schema if not exists private;

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
  position integer not null default 0 check (position >= 0),
  created_at timestamptz not null default now(),
  primary key (user_id, video_id)
);

create index videos_published_created_idx on public.videos (published, created_at desc);
create index subscriptions_user_status_expiry_idx on public.subscriptions (user_id, status, expires_at desc);
create index watchlist_user_position_idx on public.watchlist (user_id, position);

create or replace function private.is_admin()
returns boolean
language sql stable security definer set search_path = public
as $$
  select exists (select 1 from public.profiles where id = auth.uid() and role = 'admin'::public.app_role);
$$;

create or replace function private.handle_new_user()
returns trigger
language plpgsql security definer set search_path = public
as $$
begin
  insert into public.profiles (id, username, role)
  values (new.id, coalesce(new.raw_user_meta_data ->> 'username', split_part(new.email, '@', 1)), 'subscriber');
  return new;
end;
$$;

create or replace function private.touch_updated_at()
returns trigger language plpgsql
as $$ begin new.updated_at = now(); return new; end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
for each row execute function private.handle_new_user();

drop trigger if exists videos_touch_updated_at on public.videos;
create trigger videos_touch_updated_at before update on public.videos
for each row execute function private.touch_updated_at();

alter table public.profiles enable row level security;
alter table public.videos enable row level security;
alter table public.subscriptions enable row level security;
alter table public.favorites enable row level security;
alter table public.watchlist enable row level security;

create policy "Cada usuario ve su perfil" on public.profiles
for select using (id = auth.uid() or private.is_admin());
create policy "El catálogo publicado es visible" on public.videos
for select using (published = true or private.is_admin());
create policy "El equipo administra el catálogo" on public.videos
for all using (private.is_admin()) with check (private.is_admin());
create policy "Cada usuario ve sus suscripciones" on public.subscriptions
for select using (user_id = auth.uid() or private.is_admin());
create policy "El equipo administra suscripciones" on public.subscriptions
for select using (private.is_admin());
create policy "Cada usuario administra sus favoritos" on public.favorites
for all using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "Cada usuario ve su lista" on public.watchlist
for select using (user_id = auth.uid());

create or replace function public.set_watchlist(video_ids uuid[])
returns void
language plpgsql security definer set search_path = public
as $$
declare current_user_id uuid := auth.uid();
begin
  if current_user_id is null then raise exception 'No autenticado'; end if;
  delete from public.watchlist where user_id = current_user_id;
  insert into public.watchlist (user_id, video_id, position)
  select current_user_id, item.video_id, item.position
  from unnest(video_ids) with ordinality as item(video_id, position)
  join public.videos on videos.id = item.video_id and videos.published;
end;
$$;

create or replace function public.activate_demo_subscription(selected_plan public.subscription_plan)
returns table (plan public.subscription_plan, expires_at timestamptz, status text)
language plpgsql security definer set search_path = public
as $$
declare current_user_id uuid := auth.uid();
declare new_expiry timestamptz := now() + interval '1 month';
begin
  if current_user_id is null then raise exception 'No autenticado'; end if;
  update public.subscriptions set status = 'cancelled'
  where user_id = current_user_id and status = 'active';
  return query insert into public.subscriptions (user_id, plan, starts_at, expires_at, status)
  values (current_user_id, selected_plan, now(), new_expiry, 'active')
  returning subscriptions.plan, subscriptions.expires_at, subscriptions.status;
end;
$$;

revoke all on function public.set_watchlist(uuid[]) from public;
grant execute on function public.set_watchlist(uuid[]) to authenticated;
revoke all on function public.activate_demo_subscription(public.subscription_plan) from public;
grant execute on function public.activate_demo_subscription(public.subscription_plan) to authenticated;

-- La primera cuenta del equipo se promueve manualmente fuera del navegador:
-- update public.profiles set role = 'admin' where id = 'UUID_DEL_USUARIO';
