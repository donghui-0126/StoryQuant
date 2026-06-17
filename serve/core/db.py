"""Supabase(Postgres) 영속 레이어 — urllib REST 만 사용 (새 의존성 0).

수집기가 news/sweep 를 upsert, 서버는 부팅 시 read.
SUPABASE_URL + SUPABASE_SERVICE_KEY 없으면 비활성(is_enabled()=False) → 호출측이 스냅샷 폴백.

테이블 (deploy/supabase-schema.sql):
  news : uid(PK) code title link paper ts sentiment substance priced_in
         llm_label llm_reason llm_comment category scope collected_at
  sweep: id(PK='kr|80') data(jsonb) ts
"""
import os
import json
import hashlib
import urllib.request
import urllib.parse

_URL = (os.environ.get('SUPABASE_URL') or '').rstrip('/')
_KEY = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ.get('SUPABASE_KEY') or ''


def is_enabled():
    return bool(_URL and _KEY)


def _req(method, path, body=None, extra_headers=None):
    url = f'{_URL}/rest/v1/{path}'
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
    headers = {
        'apikey': _KEY, 'Authorization': f'Bearer {_KEY}',
        'Content-Type': 'application/json',
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    return json.loads(raw.decode('utf-8')) if raw else None


def _uid(code, title):
    return hashlib.sha1(f'{code}|{(title or "")[:80]}'.encode('utf-8')).hexdigest()[:24]


# ───────── 쓰기 (수집기) ─────────
def upsert_news(code, articles):
    """종목 뉴스 rows 를 news 테이블에 upsert (uid 충돌 시 갱신)."""
    if not is_enabled() or not articles:
        return False
    rows = []
    for a in articles:
        rows.append({
            'uid': _uid(code, a.get('title')),
            'code': code, 'title': a.get('title'), 'link': a.get('link'),
            'paper': a.get('paper') or a.get('source'), 'ts': a.get('ts'),
            'sentiment': a.get('sentiment'), 'substance': a.get('substance'),
            'priced_in': bool(a.get('priced_in')), 'llm_label': a.get('llm_label'),
            'llm_reason': a.get('llm_reason'), 'llm_comment': a.get('llm_comment'),
            'category': a.get('category'), 'scope': a.get('scope'),
        })
    try:
        # 배치 (Supabase POST는 array upsert)
        for i in range(0, len(rows), 500):
            _req('POST', 'news?on_conflict=uid', rows[i:i+500],
                 {'Prefer': 'resolution=merge-duplicates,return=minimal'})
        return True
    except Exception as e:
        print(f'[DB] upsert_news {code} 실패: {str(e)[:120]}')
        return False


def upsert_sweep(key, data):
    """sweep 집계 blob 을 sweep 테이블에 upsert (id 당 1행)."""
    if not is_enabled():
        return False
    try:
        _req('POST', 'sweep?on_conflict=id',
             [{'id': key, 'data': data, 'ts': 'now()'}],
             {'Prefer': 'resolution=merge-duplicates,return=minimal'})
        return True
    except Exception as e:
        print(f'[DB] upsert_sweep {key} 실패: {str(e)[:120]}')
        return False


# ───────── 읽기 (서버 부팅) ─────────
def fetch_latest_sweep(key):
    """sweep blob 1건."""
    if not is_enabled():
        return None
    try:
        rows = _req('GET', f'sweep?id=eq.{urllib.parse.quote(key)}&select=data,ts&limit=1')
        return rows[0] if rows else None
    except Exception as e:
        print(f'[DB] fetch_sweep {key} 실패: {str(e)[:120]}')
        return None


def fetch_all_news():
    """전체 news 를 {code: [articles]} 로. ts 내림차순."""
    if not is_enabled():
        return {}
    out = {}
    try:
        offset = 0
        while True:
            rows = _req('GET',
                        'news?select=code,title,link,paper,ts,sentiment,substance,priced_in,'
                        'llm_label,llm_reason,llm_comment,category,scope'
                        f'&order=ts.desc&limit=1000&offset={offset}')
            if not rows:
                break
            for r in rows:
                out.setdefault(r['code'], []).append(r)
            if len(rows) < 1000:
                break
            offset += 1000
        return out
    except Exception as e:
        print(f'[DB] fetch_all_news 실패: {str(e)[:120]}')
        return out
