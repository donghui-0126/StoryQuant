-- StoryQuant Supabase 스키마
-- Supabase 대시보드 → SQL Editor 에 붙여넣고 실행하세요.
-- 이후 서버 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY (Settings → API)

-- ─── 뉴스 (종목별 헤드라인 + LLM 분류·한줄평) ───
create table if not exists news (
  uid         text primary key,           -- sha1(code|title)
  code        text not null,
  title       text,
  link        text,
  paper       text,
  ts          bigint,                      -- 기사 시각 (epoch ms)
  sentiment   text,                        -- bull / bear / neut
  substance   text,                        -- substantive / reactive / neutral
  priced_in   boolean default false,
  llm_label   text,                        -- event_bull / event_bear / reactive / speculative / off_topic
  llm_reason  text,                        -- 분류 근거
  llm_comment text,                        -- 전문가 한줄평
  category    text,
  scope       text,                        -- stock / sector / macro
  collected_at timestamptz default now()
);
create index if not exists news_code_idx on news (code);
create index if not exists news_ts_idx   on news (ts desc);

-- ─── 종목 sweep 집계 (피드용 blob) ───
create table if not exists sweep (
  id   text primary key,                   -- 예: 'kr|80'
  data jsonb,
  ts   timestamptz default now()
);

-- ─── 읽기 공개 (anon SELECT 허용) · 쓰기는 service_key 전용 ───
alter table news  enable row level security;
alter table sweep enable row level security;
drop policy if exists news_read  on news;
drop policy if exists sweep_read on sweep;
create policy news_read  on news  for select using (true);
create policy sweep_read on sweep for select using (true);
-- service_role 키는 RLS 우회 → 수집기 insert/upsert 는 그대로 동작.
