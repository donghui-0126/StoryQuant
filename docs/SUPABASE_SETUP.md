# StoryQuant — Supabase 영구 DB + Google 로그인 셋업 (zero → end)

이 문서 하나로 ① 뉴스/종목 영구 저장(콜드스타트 제거) ② Google 로그인까지 끝냅니다.
순서대로 따라 하세요. **★ = 당신만 할 수 있는 것 (계정/키), 나머지 코드는 이미 다 되어 있음.**

소요: 약 25~30분. 필요한 계정: Supabase(무료), Google(이미 있음), Render(이미 함).

---

## 0. 큰 그림

```
[수집기(Render 백엔드, 주기적)]            [Supabase]                 [브라우저]
뉴스 fetch → LLM 분류·한줄평 ── insert ──▶  Postgres(news/sweep)  ── 부팅 시 read ──▶ 보여주기만
                                            Auth(Google)         ◀── 로그인 ───────  사용자
```
- **DB**: 서버 밖에 영구 보존 → 재부팅해도 즉시 서빙(콜드 0), 반복 LLM 비용 0
- **Auth**: Supabase가 Google OAuth를 대행 → 프론트는 버튼만

준비물 3개를 끝에 채우면 됩니다:
1. `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` → **Render 환경변수** (백엔드 DB 쓰기)
2. `SUPABASE_URL` / `anon key` → **shorts.html** (프론트 로그인)
3. Google OAuth Client ID/Secret → **Supabase Auth** (구글 로그인)

---

## 1. ★ Supabase 프로젝트 생성 (5분)

1. https://supabase.com → **Sign in with GitHub** → **New project**
2. 입력:
   - Name: `storyquant`
   - Database Password: 아무거나 (강하게) — 메모해두기
   - Region: **Northeast Asia (Seoul)** 권장
3. **Create new project** → 1~2분 프로비저닝 대기

---

## 2. ★ DB 스키마 만들기 (2분)

1. 좌측 메뉴 **SQL Editor** → **New query**
2. 레포의 `deploy/supabase-schema.sql` 내용을 **전부 복사해서 붙여넣기**
3. **Run** (▶) → "Success" 확인
   - `news`, `sweep` 테이블 + 공개 읽기 정책이 생성됩니다.
4. 좌측 **Table Editor** 에서 `news`, `sweep` 테이블이 보이면 OK.

> 스키마 파일 위치: `StoryQuant/deploy/supabase-schema.sql`

---

## 3. ★ API 키 복사 (1분)

좌측 **Settings(⚙️) → API** 에서 3개를 복사해 메모:

| 항목 | 어디에 쓰나 | 공개해도 되나 |
|---|---|---|
| **Project URL** (`https://xxx.supabase.co`) | Render + shorts.html 둘 다 | ✅ |
| **anon public** 키 | shorts.html (프론트 로그인) | ✅ 공개 안전 |
| **service_role** 키 | Render (백엔드 DB 쓰기) | ❌ **절대 프론트/깃에 넣지 말 것** |

---

## 4. ★ 백엔드(Render)에 DB 연결 (3분)

Render 대시보드 → `storyquant` 서비스 → **Environment** → 아래 2개 추가:

| Key | Value |
|---|---|
| `SUPABASE_URL` | (3번의 Project URL) |
| `SUPABASE_SERVICE_KEY` | (3번의 **service_role** 키) |

**Save changes** → 자동 재배포.

배포 후 Render **Logs** 에서 다음이 보이면 성공:
```
[DB] news N종목 로드        ← DB에서 읽음 (처음엔 0, 첫 수집 후 채워짐)
[Refresh] kr|80 갱신·저장 ... ← 수집기가 DB에 insert
```
- 처음엔 DB가 비어 있어 수집기가 채웁니다(수 분). 이후 **모든 부팅에서 DB를 즉시 읽어** 콜드 0.

---

## 5. ★ Google OAuth 만들기 (Google Cloud Console, 8분)

구글 로그인은 Supabase가 대행하지만, **구글 쪽에서 OAuth 앱을 발급**받아야 합니다.

1. https://console.cloud.google.com → 프로젝트 생성(또는 기존) → 상단에서 선택
2. **APIs & Services → OAuth consent screen**
   - User Type: **External** → Create
   - App name: `StoryQuant`, 지원 이메일/개발자 이메일: 본인 메일
   - Scopes: 그냥 Save and Continue (기본)
   - Test users: 본인 구글 이메일 추가 (게시 전 테스트용)
   - Save
3. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   - Application type: **Web application**
   - Name: `StoryQuant Web`
   - **Authorized redirect URIs** 에 아래를 추가 (★중요):
     ```
     https://<당신-프로젝트>.supabase.co/auth/v1/callback
     ```
     (Supabase Project URL 의 호스트 + `/auth/v1/callback`)
   - **Create** → **Client ID** 와 **Client Secret** 복사

---

## 6. ★ Supabase에 Google 연결 (2분)

1. Supabase 좌측 **Authentication → Sign In / Providers → Google**
2. **Google enabled** 켜기
3. 5번에서 받은 **Client ID**, **Client Secret** 붙여넣기 → **Save**
4. **Authentication → URL Configuration**:
   - **Site URL**: `https://storyquant.onrender.com`
   - **Redirect URLs** 에 추가 (Add URL):
     ```
     https://storyquant.onrender.com/shorts.html
     https://storyquant.onrender.com/**
     ```
   - (로컬 테스트도 하려면 `http://127.0.0.1:8765/**` 도 추가)
   - **Save**

---

## 7. ★ 프론트에 Supabase 연결 (2분)

`StoryQuant/shorts.html` 상단의 설정 블록(파일 맨 위쪽)에서 두 줄만 채웁니다:

```js
window.SQ_SUPABASE_URL = "https://<당신-프로젝트>.supabase.co";
window.SQ_SUPABASE_KEY = "<anon public 키>";   // service_role 아님!
```
> `<!-- ▼▼ Supabase 설정 ... ▼▼ -->` 주석 블록을 찾으면 됩니다.
> anon 키는 공개 안전하므로 깃에 커밋해도 됩니다. (service_role 키는 절대 여기 넣지 마세요.)

저장 후 커밋·푸시 → Render 재배포:
```bash
git add shorts.html && git commit -m "Connect Supabase (auth)" && git push
```

---

## 8. 확인 (zero → end 완료)

1. **로그인**: `https://storyquant.onrender.com/shorts.html` → 하단 **나 탭** → "Google로 계속하기"
   → 구글 로그인 → 돌아오면 프로필(이름·사진) 표시되면 ✅
2. **DB 영속**: Render를 한 번 **Manual Deploy(또는 15분 방치 후 재접속)** → 로딩이 즉시 뜨면 ✅
   - Render Logs 에 `[DB] news N종목 로드` 가 보이면 DB에서 읽는 것
3. **DB 내용 눈으로**: Supabase **Table Editor → news** 에 행이 쌓이는지 확인

---

## 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| 구글 로그인 후 "redirect 오류" | 6번 Redirect URLs 에 실제 접속 주소가 빠짐 → 정확히 추가 |
| "provider is not enabled" | 6번 Google provider 안 켜짐 |
| Google "redirect_uri_mismatch" | 5번 Authorized redirect URI 가 `…supabase.co/auth/v1/callback` 와 정확히 일치해야 함 |
| 로그인은 되는데 DB 비어 있음 | 정상 — 수집기가 채우는 데 수 분. Logs 의 `[Refresh] … 갱신·저장` 기다리기 |
| `[DB] … 실패` 로그 | service_role 키 오타 / 스키마 미실행 → 2·4번 재확인 |
| 비용 걱정 | OpenAI 대시보드 → **Usage limits** 로 월 한도 설정 (예: $5). `WARM_UNIVERSE=0` 로 전체 웜업 끄기 가능 |

---

## 정리: 어디에 무엇을 넣었나

| 값 | 위치 | 비고 |
|---|---|---|
| Project URL | Render env `SUPABASE_URL` + shorts.html | 공개 OK |
| anon key | shorts.html `SQ_SUPABASE_KEY` | 공개 OK (프론트 로그인) |
| **service_role key** | Render env `SUPABASE_SERVICE_KEY` | **비밀** (백엔드 DB 쓰기) |
| Google Client ID/Secret | Supabase Auth → Google | Supabase가 보관 |

이 4개만 제자리에 들어가면 — 영구 DB + 구글 로그인 끝. 콜드스타트도 사라집니다.
막히면 어느 단계에서 무슨 메시지인지 알려주세요.
