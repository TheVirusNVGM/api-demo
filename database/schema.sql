-- WARNING: This schema is for context only and is not meant to be run.

-- Table order and constraints may not be valid for execution.

CREATE TABLE public.ai_sort_sessions (
  id text NOT NULL DEFAULT lpad((nextval('ai_sort_sessions_id_seq'::regclass))::text, 7, '0'::text),
  created_at timestamp with time zone DEFAULT now(),
  mc_version text NOT NULL,
  mod_loader text NOT NULL,
  creativity double precision NOT NULL,
  user_prompt text,
  input_mods jsonb NOT NULL,
  categories jsonb NOT NULL,
  rating integer CHECK (rating >= 1 AND rating <= 5),
  feedback_submitted_at timestamp with time zone,
  learning_status jsonb DEFAULT '{"status": "pending"}'::jsonb,
  CONSTRAINT ai_sort_sessions_pkey PRIMARY KEY (id)
);

CREATE TABLE public.crash_doctor_sessions (
  id integer NOT NULL DEFAULT nextval('crash_doctor_sessions_id_seq'::regclass),
  user_id uuid NOT NULL,
  crash_log text NOT NULL,
  game_log text,
  mc_version character varying,
  mod_loader character varying,
  root_cause text NOT NULL,
  confidence numeric NOT NULL CHECK (confidence >= 0::numeric AND confidence <= 1::numeric),
  suggestions jsonb NOT NULL DEFAULT '[]'::jsonb,
  warnings jsonb DEFAULT '[]'::jsonb,
  board_state jsonb NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT crash_doctor_sessions_pkey PRIMARY KEY (id),
  CONSTRAINT crash_doctor_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);

CREATE TABLE public.download_stats (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid,
  launcher_version text NOT NULL,
  os text NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT timezone('utc'::text, now()),
  CONSTRAINT download_stats_pkey PRIMARY KEY (id),
  CONSTRAINT download_stats_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);

CREATE TABLE public.friend_requests (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  from_user_id uuid,
  to_user_id uuid,
  status text DEFAULT 'pending'::text CHECK (status = ANY (ARRAY['pending'::text, 'accepted'::text, 'declined'::text])),
  message text,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT friend_requests_pkey PRIMARY KEY (id),
  CONSTRAINT fk_from_user FOREIGN KEY (from_user_id) REFERENCES public.users(id),
  CONSTRAINT fk_to_user FOREIGN KEY (to_user_id) REFERENCES public.users(id),
  CONSTRAINT friend_requests_from_user_id_fkey FOREIGN KEY (from_user_id) REFERENCES public.users(id),
  CONSTRAINT friend_requests_to_user_id_fkey FOREIGN KEY (to_user_id) REFERENCES public.users(id)
);

CREATE TABLE public.friends (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid,
  friend_id uuid,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT friends_pkey PRIMARY KEY (id),
  CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES public.users(id),
  CONSTRAINT fk_friend FOREIGN KEY (friend_id) REFERENCES public.users(id),
  CONSTRAINT friends_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id),
  CONSTRAINT friends_friend_id_fkey FOREIGN KEY (friend_id) REFERENCES public.users(id)
);

CREATE TABLE public.game_sessions (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  host_user_id uuid,
  session_name text NOT NULL,
  minecraft_version text NOT NULL,
  mod_loader text NOT NULL,
  max_players integer DEFAULT 10,
  current_players integer DEFAULT 1,
  is_private boolean DEFAULT false,
  password text,
  host_ip text,
  host_port integer,
  p2p_data jsonb,
  status text DEFAULT 'waiting'::text CHECK (status = ANY (ARRAY['waiting'::text, 'active'::text, 'closed'::text])),
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT game_sessions_pkey PRIMARY KEY (id),
  CONSTRAINT game_sessions_host_user_id_fkey FOREIGN KEY (host_user_id) REFERENCES public.users(id)
);

CREATE TABLE public.modpack_builds (
  id text NOT NULL DEFAULT lpad((nextval('modpack_builds_id_seq'::regclass))::text, 7, '0'::text),
  created_at timestamp with time zone DEFAULT now(),
  title text NOT NULL,
  prompt text NOT NULL,
  mc_version text NOT NULL,
  mod_loader text NOT NULL,
  pack_archetype text,
  architecture jsonb NOT NULL,
  feedback jsonb,
  learning_status jsonb DEFAULT '{"status": "pending"}'::jsonb,
  CONSTRAINT modpack_builds_pkey PRIMARY KEY (id)
);

CREATE TABLE public.modpacks (
  id bigint NOT NULL DEFAULT nextval('modpacks_id_seq'::regclass),
  source_id text NOT NULL UNIQUE,
  title text NOT NULL,
  description text,
  slug text,
  mods_by_version jsonb NOT NULL,
  mc_versions ARRAY NOT NULL,
  loaders ARRAY NOT NULL,
  category text,
  followers integer DEFAULT 0,
  downloads integer DEFAULT 0,
  summary text,
  architecture jsonb,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  parsed_at timestamp with time zone,
  modrinth_url text,
  icon_url text,
  resource_packs jsonb DEFAULT '[]'::jsonb,
  shader_packs jsonb DEFAULT '[]'::jsonb,
  architecture_readable jsonb,
  embedding USER-DEFINED,
  CONSTRAINT modpacks_pkey PRIMARY KEY (id)
);

CREATE TABLE public.mods (
  id bigint NOT NULL DEFAULT nextval('mods_id_seq'::regclass),
  source_id text NOT NULL UNIQUE,
  slug text NOT NULL UNIQUE,
  name text NOT NULL,
  description text,
  summary text,
  icon_url text,
  loaders ARRAY DEFAULT '{}'::text[],
  mc_versions ARRAY DEFAULT '{}'::text[],
  env text,
  project_type text DEFAULT 'mod'::text,
  modrinth_categories ARRAY DEFAULT '{}'::text[],
  tags jsonb DEFAULT '[]'::jsonb,
  downloads bigint DEFAULT 0,
  followers integer DEFAULT 0,
  quality_score double precision,
  source text DEFAULT 'modrinth'::text,
  last_updated timestamp with time zone,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  links jsonb DEFAULT '{}'::jsonb,
  dependencies jsonb DEFAULT '[]'::jsonb,
  incompatibilities jsonb DEFAULT '{}'::jsonb,
  capabilities ARRAY DEFAULT '{}'::text[],
  embedding USER-DEFINED,
  CONSTRAINT mods_pkey PRIMARY KEY (id)
);

CREATE TABLE public.oauth_apps (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  client_id text NOT NULL UNIQUE,
  name text NOT NULL,
  redirect_uri text NOT NULL,
  scopes ARRAY DEFAULT ARRAY['profile'::text],
  created_at timestamp with time zone DEFAULT timezone('utc'::text, now()),
  updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()),
  CONSTRAINT oauth_apps_pkey PRIMARY KEY (id)
);

CREATE TABLE public.oauth_codes (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  code text NOT NULL UNIQUE,
  client_id text NOT NULL,
  user_id uuid NOT NULL,
  redirect_uri text NOT NULL,
  scope text NOT NULL,
  state text,
  expires_at timestamp with time zone NOT NULL,
  created_at timestamp with time zone DEFAULT timezone('utc'::text, now()),
  updated_at timestamp with time zone DEFAULT now(),
  used boolean DEFAULT false,
  supabase_jwt_token text,
  CONSTRAINT oauth_codes_pkey PRIMARY KEY (id),
  CONSTRAINT fk_oauth_code_user FOREIGN KEY (user_id) REFERENCES public.users(id)
);

CREATE TABLE public.oauth_tokens (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  access_token text NOT NULL UNIQUE,
  refresh_token text UNIQUE,
  client_id text NOT NULL,
  user_id uuid NOT NULL,
  scope text NOT NULL,
  expires_at timestamp with time zone NOT NULL,
  created_at timestamp with time zone DEFAULT timezone('utc'::text, now()),
  updated_at timestamp with time zone DEFAULT now(),
  refresh_expires_at timestamp with time zone,
  CONSTRAINT oauth_tokens_pkey PRIMARY KEY (id),
  CONSTRAINT fk_oauth_user FOREIGN KEY (user_id) REFERENCES public.users(id),
  CONSTRAINT oauth_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);

CREATE TABLE public.p2p_invitations (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  session_id uuid,
  from_user_id uuid,
  to_user_id uuid,
  invitation_data jsonb,
  status text DEFAULT 'pending'::text CHECK (status = ANY (ARRAY['pending'::text, 'accepted'::text, 'declined'::text, 'expired'::text])),
  expires_at timestamp with time zone DEFAULT (now() + '00:10:00'::interval),
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT p2p_invitations_pkey PRIMARY KEY (id),
  CONSTRAINT p2p_invitations_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.game_sessions(id)
);

CREATE TABLE public.project_mods (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL,
  mod_id text NOT NULL,
  mod_name text NOT NULL,
  version text NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  position_x double precision DEFAULT 0,
  position_y double precision DEFAULT 0,
  category text,
  created_at timestamp with time zone NOT NULL DEFAULT timezone('utc'::text, now()),
  CONSTRAINT project_mods_pkey PRIMARY KEY (id),
  CONSTRAINT project_mods_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id)
);

CREATE TABLE public.projects (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  name text NOT NULL,
  minecraft_version text NOT NULL,
  loader text NOT NULL CHECK (loader = ANY (ARRAY['fabric'::text, 'forge'::text, 'quilt'::text, 'neoforge'::text])),
  created_at timestamp with time zone NOT NULL DEFAULT timezone('utc'::text, now()),
  updated_at timestamp with time zone NOT NULL DEFAULT timezone('utc'::text, now()),
  CONSTRAINT projects_pkey PRIMARY KEY (id),
  CONSTRAINT projects_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);

CREATE TABLE public.session_participants (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  session_id uuid,
  user_id uuid,
  status text DEFAULT 'invited'::text CHECK (status = ANY (ARRAY['invited'::text, 'joined'::text, 'left'::text, 'kicked'::text])),
  p2p_connection_data jsonb,
  joined_at timestamp with time zone DEFAULT now(),
  CONSTRAINT session_participants_pkey PRIMARY KEY (id),
  CONSTRAINT session_participants_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.game_sessions(id)
);

CREATE TABLE public.test_keys (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  key text NOT NULL UNIQUE,
  user_id uuid,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  used_at timestamp with time zone,
  CONSTRAINT test_keys_pkey PRIMARY KEY (id),
  CONSTRAINT test_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);

CREATE TABLE public.user_status (
  user_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'offline'::text CHECK (status = ANY (ARRAY['online'::text, 'offline'::text, 'away'::text])),
  current_game text,
  is_playing boolean DEFAULT false,
  last_seen timestamp with time zone DEFAULT now(),
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now(),
  CONSTRAINT user_status_pkey PRIMARY KEY (user_id),
  CONSTRAINT fk_user_status FOREIGN KEY (user_id) REFERENCES public.users(id),
  CONSTRAINT user_status_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id)
);

CREATE TABLE public.users (
  id uuid NOT NULL,
  email text NOT NULL UNIQUE,
  name text,
  subscription_tier text NOT NULL DEFAULT 'free'::text CHECK (subscription_tier = ANY (ARRAY['free'::text, 'test'::text, 'premium'::text, 'pro'::text])),
  created_at timestamp with time zone NOT NULL DEFAULT timezone('utc'::text, now()),
  updated_at timestamp with time zone NOT NULL DEFAULT timezone('utc'::text, now()),
  avatar_url text,
  custom_username text UNIQUE CHECK (custom_username IS NULL OR custom_username ~ '^[a-zA-Z0-9_]{3,20}$'::text),
  has_custom_username boolean DEFAULT false,
  daily_requests_used integer DEFAULT 0,
  monthly_requests_used integer DEFAULT 0,
  ai_tokens_used integer DEFAULT 0,
  last_request_date date,
  custom_limits jsonb,
  CONSTRAINT users_pkey PRIMARY KEY (id),
  CONSTRAINT users_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id)
);

