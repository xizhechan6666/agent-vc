-- Agent VC durable storage.
-- Safe to run more than once in Supabase SQL Editor.

create table if not exists public.evaluations (
  id bigserial primary key,
  created_at text not null default (now()::text),
  project_name text not null,
  total_score integer not null,
  recommendation text not null,
  raw_eligible integer not null,
  final_candidate integer not null,
  batch_index integer not null,
  project_fingerprint text,
  submitter_key text,
  duplicate_today integer not null default 0,
  contact_hint text,
  report_token text,
  owner_preview integer not null default 0,
  project_json text,
  answers_json text,
  payer_wallet text,
  source text,
  report_url text,
  report_json text not null
);

create index if not exists idx_evaluations_report_token
  on public.evaluations (report_token);

create index if not exists idx_evaluations_created_at
  on public.evaluations (created_at);

create index if not exists idx_evaluations_fingerprint
  on public.evaluations (project_fingerprint);

create index if not exists idx_evaluations_submitter_key
  on public.evaluations (submitter_key);

alter table public.evaluations enable row level security;

-- The application writes through a server-side Postgres connection string.
-- No public Data API access is required for this table.
