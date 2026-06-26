-- Run this in your Supabase SQL editor

create table if not exists projects (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists intersections (
  id           uuid primary key default gen_random_uuid(),
  project_id   uuid references projects(id) on delete cascade,
  int_id       text,
  ns_street    text,
  ew_street    text,
  am_volumes   jsonb,
  pm_volumes   jsonb,
  svg_am       text,
  svg_pm       text,
  svg_both     text,
  x            float default 60,
  y            float default 60,
  sort_order   int default 0
);

create table if not exists connectors (
  id                   uuid primary key default gen_random_uuid(),
  project_id           uuid references projects(id) on delete cascade,
  from_intersection_id uuid references intersections(id) on delete cascade,
  from_side            text,
  to_intersection_id   uuid references intersections(id) on delete cascade,
  to_side              text,
  direction            text
);

-- Enable RLS
alter table projects      enable row level security;
alter table intersections enable row level security;
alter table connectors    enable row level security;

-- Allow authenticated users to read/write all rows
-- (tighten per-org later if needed)
create policy "auth read projects"      on projects      for select using (auth.role() = 'authenticated');
create policy "auth insert projects"    on projects      for insert with check (auth.role() = 'authenticated');
create policy "auth update projects"    on projects      for update using (auth.role() = 'authenticated');
create policy "auth delete projects"    on projects      for delete using (auth.role() = 'authenticated');

create policy "auth read intersections"   on intersections for select using (auth.role() = 'authenticated');
create policy "auth insert intersections" on intersections for insert with check (auth.role() = 'authenticated');
create policy "auth update intersections" on intersections for update using (auth.role() = 'authenticated');
create policy "auth delete intersections" on intersections for delete using (auth.role() = 'authenticated');

create policy "auth read connectors"   on connectors for select using (auth.role() = 'authenticated');
create policy "auth insert connectors" on connectors for insert with check (auth.role() = 'authenticated');
create policy "auth delete connectors" on connectors for delete using (auth.role() = 'authenticated');

-- Realtime
alter publication supabase_realtime add table intersections;
alter publication supabase_realtime add table connectors;
