# StoryQuant — 내 PC에서 실배포 (고정 URL, 콜드스타트 0)

Render 무료 티어 대신 **내 컴퓨터를 백엔드로** 돌립니다.
장점: 빠른 CPU + **영구 디스크 → 재웜업/콜드스타트 없음** + 무료.
단점: **PC가 켜져 있을 때만** 접속 가능.

> 핵심 아이디어: 집 PC를 외부에 직접 열지 않고(포트포워딩·도메인 불필요),
> Cloudflare Worker가 **고정 주소**(`storyquant.<계정>.workers.dev`)를 주고,
> 그 뒤를 내 PC의 cloudflared 터널로 프록시. 터널 주소가 바뀌어도 자동 갱신.

---

## 0. 준비물
- 이 레포 (`StoryQuant`), Python venv 세팅 완료(`.venv`)
- `OPENAI_API_KEY` 가 `.env` 에 있음
- Node/npx (cloudflared·wrangler 용), cloudflared 설치
- Cloudflare 계정 (무료) — 도메인 없어도 됨

---

## 1. ★ Cloudflare 로그인 (1회, 5분)

```bash
npx wrangler login
```
브라우저 열리면 **Allow**. (Cloudflare 계정 없으면 무료 가입)

---

## 2. ★ Worker 배포 = 고정 주소 발급 (1회, 3분)

```bash
cd ~/StoryQuant        # (WSL 기준; Windows면 repo 경로)
bash deploy/setup.sh
```
이게 자동으로:
- KV 네임스페이스 생성 → `worker/wrangler.toml` 에 id 주입
- `shorts.html` 등 정적 파일을 `worker/public` 으로 빌드
- Worker 배포 → **고정 주소 출력**: `https://storyquant.<당신계정>.workers.dev`

이 주소를 메모. (이게 영구 공개 URL — 절대 안 바뀜)

---

## 3. 백엔드 + 터널 켜기 (매번 PC에서)

터미널 2개(또는 백그라운드):

```bash
# (A) 백엔드 서버
cd ~/StoryQuant
.venv/bin/python serve.py 8765

# (B) 터널 + 자동 KV 갱신 (Worker가 항상 내 PC를 가리키게)
bash deploy/tunnel-keeper.sh
```
- `tunnel-keeper.sh` 는 cloudflared 터널을 띄우고, 터널 주소가 바뀔 때마다
  Worker 의 KV(`api_origin`)를 자동 갱신 → 고정 주소는 그대로 내 PC로 연결.
- 터널이 끊겨도 자동 재시작 + 재등록.

> 항상 켜두려면: 두 명령을 PC 부팅 시 자동 실행되게 등록(작업 스케줄러/서비스).
> 필요하면 요청하세요 — Windows 자동시작용 배치도 만들어 드릴게요.

---

## 4. ★ GitHub Pages 데모 버튼을 이 주소로

`docs/index.html` 의 한 줄을 Worker 고정 주소로 변경:
```js
var DEMO_URL = "https://storyquant.<당신계정>.workers.dev/shorts.html";
```
커밋·푸시:
```bash
git add docs/index.html && git commit -m "Point demo to self-hosted Worker" && git push
```
프로필/랜딩의 "라이브 데모"가 이제 내 PC(고정 주소)로 연결됩니다.

---

## 5. 콜드스타트가 왜 사라지나
- PC 디스크는 안 날아가서 `seed/` + `data/snapshots/` 스냅샷이 그대로 살아있음
  → 부팅 시 즉시 로드, 재웜업 불필요.
- 첫 1회만 universe 웜업(수 분) 후 디스크에 저장 → 이후 영구.

---

## 6. DB(Supabase)는 선택
- **콜드스타트 해결**만 목적이면 → PC 자가호스팅으로 이미 해결, Supabase DB 불필요.
- **Google 로그인** 쓸 거면 → `SUPABASE_SETUP.md` 의 1·3·5·6·7번만(Auth 부분) 하면 됨.
  (DB 영속 부분 2·4번은 건너뛰어도 됨)

---

## 자주 묻는 것

| Q | A |
|---|---|
| PC 꺼지면? | 앱 다운. 항상 떠 있어야 하면 안 끄거나, 저전력 미니PC/라즈베리파이 권장 |
| 보안 위험? | 포트포워딩 안 함(터널이 아웃바운드 연결) → 라우터 노출 없음. 안전한 편 |
| Render는 버려? | 백업으로 둬도 됨. 데모 URL만 Worker로 바꾸면 주력은 PC |
| IP 바뀌어도? | tunnel-keeper 가 자동 재등록 → 고정 URL 유지 |
| 더 안정적으로? | 도메인 사서 Cloudflare named tunnel → `app.내도메인.com` (선택) |

---

요약: **`wrangler login` → `deploy/setup.sh`(고정주소) → serve.py + tunnel-keeper.sh(상시) → 데모 URL 교체.**
PC만 켜져 있으면 Render보다 빠르고 콜드도 없어요.
