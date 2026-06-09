# StoryQuant — Supabase 통합 가이드

shorts.html의 커뮤니티(댓글)·로그인을 **로컬 prototype → 클라우드 multi-user** 로 활성화하는 가이드.

> **현재 상태**: Supabase URL/key 미설정 → localStorage fallback (한 기기에만 저장됨)
> **목표**: 진짜 multi-user 댓글 + 익명 Auth 활성화

---

## 1. Supabase 프로젝트 만들기 (10분)

1. https://supabase.com 가입 (GitHub/Google 로그인 가능, 무료)
2. **New Project** 생성
   - Name: `storyquant` (자유)
   - Region: **Northeast Asia (Seoul)** 권장
   - Database password: 강력하게 설정 (메모해두기)
3. 프로젝트 생성 완료 후 좌측 메뉴 **Settings → API**:
   - `Project URL`: `https://xxxx.supabase.co`
   - `anon public` key: `eyJhbGc...` (긴 JWT)
   - 위 두 값을 메모 (anon key는 **클라이언트 노출 OK**, service_role key는 절대 노출 X)

---

## 2. DB 스키마 + RLS 정책 SQL

Supabase 좌측 메뉴 **SQL Editor** → 새 쿼리 → 아래 SQL 전체 복사 → **Run**.

```sql
-- ─────────────────────────────────────────────────────────────
-- StoryQuant comments 테이블 + RLS (Row Level Security)
-- ─────────────────────────────────────────────────────────────

-- 1) 테이블 생성
create table if not exists comments (
  id          uuid primary key default gen_random_uuid(),
  scope       text not null,
  user_id     uuid references auth.users(id) on delete cascade,
  user_name   text not null,
  text        text not null,
  ts          timestamptz not null default now()
);

-- 2) 인덱스 (조회 성능)
create index if not exists comments_scope_ts_idx on comments(scope, ts desc);
create index if not exists comments_user_idx on comments(user_id);

-- 3) 입력 검증 (DB 단)
alter table comments add constraint comments_text_len_chk
  check (char_length(text) between 1 and 200);
alter table comments add constraint comments_user_name_len_chk
  check (char_length(user_name) between 2 and 16);
alter table comments add constraint comments_scope_fmt_chk
  check (scope ~ '^(stock_|sector_)[a-zA-Z0-9_-]+$');

-- 4) RLS 활성화
alter table comments enable row level security;

-- 5) 정책 — SELECT (모두 공개 댓글)
create policy "anyone can read comments"
  on comments for select
  using (true);

-- 6) 정책 — INSERT (로그인한 본인만, user_id는 자기 auth.uid())
create policy "users can insert own comments"
  on comments for insert
  with check (auth.uid() = user_id);

-- 7) 정책 — UPDATE (본인만)
create policy "users can update own comments"
  on comments for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- 8) 정책 — DELETE (본인만)
create policy "users can delete own comments"
  on comments for delete
  using (auth.uid() = user_id);

-- 9) trigger — INSERT 시 user_id 자동 채우기 (편의)
create or replace function fill_comment_user_id()
returns trigger language plpgsql security definer as $$
begin
  if new.user_id is null then
    new.user_id := auth.uid();
  end if;
  return new;
end $$;

drop trigger if exists set_comment_user_id on comments;
create trigger set_comment_user_id
  before insert on comments
  for each row execute function fill_comment_user_id();
```

이것만 실행하면 **DB·RLS·검증·trigger 모두 셋업 완료**.

---

## 3. Google OAuth 활성화 (필수)

shorts.html은 Google 로그인을 기본으로 사용합니다. 셋업 두 단계.

### 3-A. Google Cloud Console — OAuth 클라이언트 ID 만들기 (5분)

1. https://console.cloud.google.com 접속
2. 상단 프로젝트 선택 → **새 프로젝트** (이름: StoryQuant)
3. 좌측 메뉴 **APIs & Services → OAuth consent screen**:
   - User Type: **External** 선택 → 만들기
   - App name: `StoryQuant`
   - User support email: 본인 이메일
   - App domain (선택, 빈칸 OK)
   - Developer contact: 본인 이메일
   - Scope: **email · profile · openid** 만 추가 (다른 거 X)
   - Test users: 본인 + 베타 사용자 이메일 추가 (정식 publish 전엔 테스트 모드)
4. **APIs & Services → Credentials → CREATE CREDENTIALS → OAuth client ID**:
   - Application type: **Web application**
   - Name: `StoryQuant Web`
   - **Authorized JavaScript origins** (둘 다):
     - `http://127.0.0.1:8765`
     - `https://your-tunnel-or-domain.com` (현재 cloudflare tunnel URL)
   - **Authorized redirect URIs**:
     - `https://xxxx.supabase.co/auth/v1/callback` ⚠ Supabase 프로젝트 URL 사용
5. 만들고 나면 **Client ID** + **Client Secret** 받음 (다음 단계에 사용)

### 3-B. Supabase Dashboard — Google Provider 연결 (2분)

1. Supabase 좌측 메뉴 **Authentication → Providers → Google**
2. **Enable Sign in with Google**: ON
3. **Client ID (for OAuth)**: 위 §3-A에서 받은 Client ID 붙여넣기
4. **Client Secret (for OAuth)**: 위 §3-A의 Client Secret 붙여넣기
5. **Callback URL (for OAuth)**: 자동 표시됨 — 이것을 §3-A 4단계 Authorized redirect URIs에 넣은 게 일치하는지 확인
6. **Save**

→ 이제 shorts.html "나" 탭에서 **Google로 계속하기** 버튼 작동.

### 3-C. (선택) Anonymous Auth도 활성화

비상용 / 빠른 테스트용으로 익명도 허용하려면:
- **Authentication → Providers → Anonymous Sign-Ins**: ON

shorts.html은 Supabase 미설정 또는 익명도 fallback으로 로컬 닉네임 모드 지원하므로 익명 활성화 안 해도 됩니다.

---

## 4. 보안 추가 옵션 (권장)

### Rate Limit
Supabase Dashboard → **Settings → API → Rate Limits**:
- Auth: 기본 30 req/hour (충분)
- DB: 무제한이지만 RLS로 user 단위 제한 가능

### Allowed Origins (CORS)
**Settings → API → URL Configuration → Site URL & Redirect URLs**:
- `https://likelihood-televisions-fcc-socks.trycloudflare.com` (현재 tunnel)
- `http://127.0.0.1:8765` (로컬 개발)
- `https://your-domain.pages.dev` (Cloudflare Pages 배포 시)

### 닉네임 도용 방지
현재 user_name은 사용자 입력 닉네임. 실제 출시 시 unique 제약 추가 권장:
```sql
create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text unique not null check (char_length(username) between 2 and 16)
);
alter table profiles enable row level security;
create policy "anyone can read profiles" on profiles for select using (true);
create policy "users can insert own profile" on profiles for insert
  with check (auth.uid() = id);
```

---

## 5. 클라이언트 연결

shorts.html은 다음 두 값을 찾으면 자동으로 Supabase 모드 전환:
- `window.SQ_SUPABASE_URL`
- `window.SQ_SUPABASE_KEY`

### 방법 A — 브라우저 콘솔에서 한 번만 설정 (개발/베타)

shorts.html 열고 F12 → Console:

```js
localStorage.setItem('SQ_SUPABASE_URL', 'https://xxxx.supabase.co');
localStorage.setItem('SQ_SUPABASE_KEY', 'eyJhbGc...');
location.reload();
```

→ 콘솔에 `[Supabase] cloud mode connected` 출력되면 성공.

### 방법 B — HTML에 hardcode (배포)

shorts.html `<head>` 마지막에 추가 (Supabase **anon key**만, **service_role 절대 X**):

```html
<script>
  window.SQ_SUPABASE_URL = 'https://xxxx.supabase.co';
  window.SQ_SUPABASE_KEY = 'eyJhbGc...';
</script>
```

⚠ anon key는 클라이언트 노출 안전 (RLS로 보호됨). service_role key는 절대 클라이언트에 두지 말 것.

### 방법 C — 별도 config.js (권장)

```html
<script src="./config.js" defer></script>
```

config.js (gitignore에 추가):
```js
window.SQ_SUPABASE_URL = 'https://xxxx.supabase.co';
window.SQ_SUPABASE_KEY = 'eyJhbGc...';
```

---

## 6. 동작 확인

1. shorts.html 열기
2. 콘솔에 `[Supabase] cloud mode connected` 확인
3. "나" 탭 → **Google로 계속하기** 클릭 → Google 계정 선택 → 권한 동의
4. 페이지 자동 복귀 후 본인 Google 프로필 사진·이메일·이름 표시 + 🔐 Google 배지
5. 핫 종목 → 점수 모달 → "💬 토론" → 댓글 작성
6. 댓글 sheet 헤더에 "🌐 클라우드" 표시 (이전엔 "📱 로컬 prototype")
7. **다른 기기/브라우저**에서 같은 Google 계정으로 로그인 → 같은 닉네임·아바타·저장 종목·댓글 확인됨
8. 다른 사람이 같은 종목 토론 진입 → 다른 사람 댓글 보임 ✅ multi-user

---

## 7. 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| 콘솔에 `[Supabase] not configured — using localStorage fallback` | URL/key 안 설정됨 — 위 §5 |
| 댓글 작성 후 "전송 실패" | RLS 정책 미적용 — §2 SQL 다시 실행 |
| "not authenticated" 에러 | Anonymous Auth 비활성 — §3 |
| CORS 에러 | Allowed Origins 누락 — §4 |
| user_name이 "익명"으로 나옴 | Google scope에 `profile` 누락 — §3-A OAuth consent screen에서 scope 재확인 |
| Google 로그인 클릭 후 "Error 400: redirect_uri_mismatch" | §3-A의 Authorized redirect URIs에 Supabase callback URL이 정확히 들어갔는지 확인 |
| Google 로그인 후 "Access blocked: This app's request is invalid" | OAuth consent screen이 publish 안 됨 + 본인이 test user에 없음 — §3-A 3단계 Test users 추가 |
| 다른 브라우저에서 같은 Google 계정으로 로그인했는데 댓글 안 보임 | 댓글이 다른 scope (예: stock_005930 vs stock_005930.KS)에 저장됐을 가능성 — 콘솔 SELECT 확인 |

---

## 8. 비용

Supabase 무료 tier:
- DB 500MB
- 사용자 50,000명
- Auth 50,000 MAU
- 댓글 ~100만 건까지 무료

베타 5명 + 정식 출시 1년차도 충분.

---

## 9. 보안 체크리스트 ✅

- [x] Anon key만 클라이언트 노출, service_role 절대 X
- [x] RLS 활성화 (SELECT 공개, INSERT/UPDATE/DELETE 본인만)
- [x] DB 단 입력 검증 (text 1~200자, user_name 2~16자, scope 형식)
- [x] 클라이언트 입력 검증 (esc, 길이, 특수문자)
- [x] Rate limit (클라이언트 3초)
- [x] CSP meta tag (외부 스크립트 제한)
- [x] HTTPS only (Supabase 기본)
- [x] CORS allowed origins 명시
- [ ] (V3) 신고 기능 + 욕설 필터
- [ ] (V3) IP-level rate limit (Cloudflare WAF)
