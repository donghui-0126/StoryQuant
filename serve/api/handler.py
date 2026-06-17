"""HTTP 라우팅. 모든 /api/* 엔드포인트는 ?market=kr|us 받음 (default kr)."""
import http.server
import json
import os
import re
import time
import urllib.parse

from ..markets import get_market, list_markets
from ..core.feeds import fetch_news
from ..core.news import fetch_stock_news
from ..core.quote import fetch_stock_chart, fetch_quote
from ..core.strategy import fetch_sweep, fetch_recent_picks, walkforward_backtest
from ..core.macro import compute_macro_stress, compute_macro_beta


# 정적 파일 루트 — 이 파일(serve/api/handler.py) 기준 2단계 상위 = repo 루트.
# 배포 환경(Render 등)에서도 경로가 자동으로 맞도록 하드코딩 제거.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, fmt, *args):
        try:
            print(f'[{time.strftime("%H:%M:%S")}] {self.address_string()} "{self.requestline}" {args[1] if len(args) > 1 else "-"} -')
        except Exception:
            pass

    # ───────── routing ─────────
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == '/api/news':
            return self._api_news(u)
        if u.path == '/api/quote':
            return self._api_quote(u)
        if u.path == '/api/marketcap':
            return self._api_marketcap(u)
        if u.path == '/api/universe':
            return self._api_universe(u)
        if u.path == '/api/markets':
            return self._api_markets(u)
        if u.path == '/api/stock-news':
            return self._api_stock_news(u)
        if u.path == '/api/stock-chart':
            return self._api_stock_chart(u)
        if u.path == '/api/sweep':
            return self._api_sweep(u)
        if u.path == '/api/recent-picks':
            return self._api_recent_picks(u)
        if u.path == '/api/walkforward':
            return self._api_walkforward(u)
        if u.path == '/api/macro':
            return self._api_macro(u)
        if u.path == '/api/stock-events':
            return self._api_stock_events(u)
        if u.path == '/api/saved-digest':
            return self._api_saved_digest(u)
        if u.path == '/api/stock-one':
            return self._api_stock_one(u)
        if u.path == '/api':
            return self._api_index()
        return super().do_GET()

    STOCK_ONE_CACHE = {}
    def _api_stock_one(self, u):
        """단일 종목 카드 데이터 (sweep 1건) — 검색·섹터에서 핫 외 종목을 릴로 표시용."""
        q = urllib.parse.parse_qs(u.query)
        market = self._market(q)
        code = (q.get('code', [''])[0] or '').strip()
        if not code:
            return self._send_json({'error': 'code required'}, status=400)
        key = f'{market.id}|{code}'
        now = time.time()
        c = Handler.STOCK_ONE_CACHE.get(key)
        if c and (now - c[0]) < 600:
            return self._send_json({'cached': True, **c[1]})
        try:
            from ..core.strategy import fetch_one_for_sweep
            regime = (Handler.SWEEP_CACHE.get(f'{market.id}|200', {}).get('data') or {}).get('macro_regime', 'neutral')
            row = fetch_one_for_sweep(code, market, macro_regime=regime)
            if not row:
                return self._send_json({'error': 'no data', 'code': code}, status=404)
            row.pop('_sector_articles', None)
            news = row.pop('_news', None)
            if news:
                Handler.NEWS_SNAPSHOT[code] = news   # 이 종목 모달도 이후 DB에서 즉시 (콜드 없음)
            Handler.STOCK_ONE_CACHE[key] = (now, row)
            if len(Handler.STOCK_ONE_CACHE) > 100:
                Handler.STOCK_ONE_CACHE.pop(min(Handler.STOCK_ONE_CACHE.items(), key=lambda kv: kv[1][0])[0])
            self._send_json({'cached': False, **row})
        except Exception as e:
            self._send_json({'error': str(e)[:200]}, status=500)

    DIGEST_CACHE = {}
    def _api_saved_digest(self, u):
        """저장 종목 새 소식 — 실질 사건 뉴스 + 큰 변동. ?codes=a,b,c"""
        q = urllib.parse.parse_qs(u.query)
        market = self._market(q)
        codes = [c.strip() for c in q.get('codes', [''])[0].split(',') if c.strip()][:30]
        if not codes:
            return self._send_json({'error': 'codes required'}, status=400)
        days = max(1, min(7, int(q.get('days', ['3'])[0])))
        key = f'{market.id}|{days}|{",".join(sorted(codes))}'
        now = time.time()
        cached = Handler.DIGEST_CACHE.get(key)
        if cached and (now - cached[0]) < 600:
            return self._send_json({'cached': True, **cached[1]})
        try:
            from ..core.digest import saved_digest
            data = saved_digest(codes, market, days=days)
            Handler.DIGEST_CACHE[key] = (now, data)
            if len(Handler.DIGEST_CACHE) > 50:
                old = min(Handler.DIGEST_CACHE.items(), key=lambda kv: kv[1][0])
                Handler.DIGEST_CACHE.pop(old[0])
            self._send_json({'cached': False, **data})
        except Exception as e:
            self._send_json({'error': str(e)[:200]}, status=500)

    EVENTS_CACHE = {}
    def _api_stock_events(self, u):
        """Event-driven attribution — 일 단위 큰 변동 ↔ 직전 48h 뉴스."""
        q = urllib.parse.parse_qs(u.query)
        market = self._market(q)
        code = q.get('code', [''])[0]
        if not code:
            return self._send_json({'error': 'code required'}, status=400)
        days = max(10, min(90, int(q.get('days', ['60'])[0])))
        threshold = max(1.0, min(10.0, float(q.get('threshold', ['2.5'])[0])))
        key = f'{market.id}|{code}|{days}|{threshold}'
        now = time.time()
        cached = Handler.EVENTS_CACHE.get(key)
        if cached and (now - cached[0]) < 3600 * 6:
            return self._send_json({'cached': True, **cached[1]})
        try:
            from ..core.events import detect_events
            data = detect_events(code, market, days=days, threshold=threshold)
            Handler.EVENTS_CACHE[key] = (now, data)
            self._send_json({'cached': False, **data})
        except Exception as e:
            import traceback
            self._send_json({'error': str(e)[:200], 'trace': traceback.format_exc()[-300:]}, status=500)

    # ───────── helpers ─────────
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache, must-revalidate')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _market(self, query):
        market_id = query.get('market', ['kr'])[0]
        return get_market(market_id)

    # ───────── endpoints ─────────
    def _api_index(self):
        return self._send_json({
            'version': '21.0',
            'markets': list_markets(),
            'endpoints': {
                '/api/news':         '?sources=...&limit=80&market=kr',
                '/api/quote':        '?codes=...&interval=1m&range=1d&market=kr',
                '/api/marketcap':    '?codes=...&market=kr',
                '/api/universe':     '?market=kr',
                '/api/markets':      '— 등록된 모든 시장 + 메타',
                '/api/stock-news':   '?code=...&page=1&market=kr',
                '/api/stock-chart':  '?code=...&range=3mo&market=kr',
                '/api/sweep':        '?top_n=120&market=kr (1h cache)',
                '/api/recent-picks': '?top_n=120&market=kr (24h cache)',
                '/api/walkforward':  '?top_n=200&days=180&top_k=10&hold=10&mode=blend&universe_mode=dynamic&cat_filter=&start_offset_days=0&market=kr (24h cache)',
            },
        })

    def _api_markets(self, u):
        out = []
        for mid in list_markets():
            m = get_market(mid)
            out.append({
                'id': m.id, 'name': m.name, 'currency': m.currency,
                'tz_offset_hours': m.tz_offset_hours,
                'benchmark_symbol': m.benchmark_symbol,
                'market_open_hour': m.market_open_hour,
                'market_close_hour': m.market_close_hour,
                'locale': m.locale,
                'feeds': len(m.get_rss_feeds()),
                'universe_size': len(m.universe()),
                'categories': list(m.category_keys.keys()),
            })
        return self._send_json({'markets': out})

    NEWS_CACHE = {}
    def _api_news(self, u):
        q = urllib.parse.parse_qs(u.query)
        market = self._market(q)
        sources = (q.get('sources', [''])[0] or '').split(',')
        sources = [s.strip() for s in sources if s.strip()]
        limit = int(q.get('limit', ['80'])[0])
        force = q.get('force', ['0'])[0] == '1'
        key = f'{market.id}|{",".join(sorted(sources))}|{limit}'
        now = time.time()
        c = Handler.NEWS_CACHE.get(key)
        if c and not force and (now - c[0]) < 120:
            data = dict(c[1]); data['cached'] = True
            return self._send_json(data)
        try:
            data = fetch_news(sources, limit, market)
            Handler.NEWS_CACHE[key] = (now, data)
            data['cached'] = False
            self._send_json(data)
        except Exception as e:
            self._send_json({'error': str(e)[:200]}, status=500)

    QUOTE_CACHE = {}
    def _api_quote(self, u):
        q = urllib.parse.parse_qs(u.query)
        market = self._market(q)
        codes_raw = q.get('codes', [''])[0]
        codes = [c.strip() for c in codes_raw.split(',') if c.strip()]
        interval = q.get('interval', ['1m'])[0]
        range_ = q.get('range', ['1d'])[0]
        if not codes:
            return self._send_json({'error': 'codes required'}, status=400)
        key = f'{market.id}|{",".join(codes)}|{interval}|{range_}'
        now = time.time()
        c = Handler.QUOTE_CACHE.get(key)
        if c and (now - c[0]) < 60:
            return self._send_json(c[1])
        try:
            data = fetch_quote(codes, interval, range_, market)
            Handler.QUOTE_CACHE[key] = (now, data)
            self._send_json(data)
        except Exception as e:
            self._send_json({'error': str(e)[:200]}, status=500)

    MCAP_CACHE = {}
    def _api_marketcap(self, u):
        q = urllib.parse.parse_qs(u.query)
        market = self._market(q)
        codes_raw = q.get('codes', [''])[0]
        codes = [c.strip() for c in codes_raw.split(',') if c.strip()]
        key = f'{market.id}|{",".join(codes)}'
        now = time.time()
        c = Handler.MCAP_CACHE.get(key)
        if c and (now - c[0]) < 86400:
            return self._send_json(c[1])
        try:
            data = market.fetch_marketcap(codes)
            Handler.MCAP_CACHE[key] = (now, data)
            self._send_json(data)
        except Exception as e:
            self._send_json({'error': str(e)[:200]}, status=500)

    def _api_universe(self, u):
        q = urllib.parse.parse_qs(u.query)
        market = self._market(q)
        univ = market.universe()
        return self._send_json({
            'market': market.id,
            'count': len(univ),
            'tickers': univ,
        })

    STOCK_NEWS_CACHE = {}
    def _api_stock_news(self, u):
        q = urllib.parse.parse_qs(u.query)
        market = self._market(q)
        code = (q.get('code', [''])[0] or '').strip()
        page = int(q.get('page', ['1'])[0])
        page_size = max(10, min(60, int(q.get('page_size', ['40'])[0])))
        if not code:
            return self._send_json({'error': 'code required'}, status=400)
        # ① DB(NEWS_SNAPSHOT) 우선 — 수집 때 분류·한줄평까지 끝낸 데이터를 그대로 읽음 (LLM 호출 0, 콜드 없음)
        snap = Handler.NEWS_SNAPSHOT.get(code)
        if page == 1 and snap:
            return self._send_json({'code': code, 'page': 1, 'articles': snap,
                                    'total': len(snap), 'source': 'snapshot'})
        # ② 스냅샷에 없는 종목(검색한 비-수집 종목)만 live fetch (fallback)
        key = f'{market.id}|{code}|{page}|{page_size}'
        now = time.time()
        c = Handler.STOCK_NEWS_CACHE.get(key)
        if c and (now - c[0]) < 120:
            return self._send_json(c[1])
        try:
            data = fetch_stock_news(code, page=page, page_size=page_size, market=market, use_llm=True)
            Handler.STOCK_NEWS_CACHE[key] = (now, data)
            if len(Handler.STOCK_NEWS_CACHE) > 100:
                old = min(Handler.STOCK_NEWS_CACHE.items(), key=lambda kv: kv[1][0])
                Handler.STOCK_NEWS_CACHE.pop(old[0])
            self._send_json(data)
        except Exception as e:
            self._send_json({'error': str(e)[:200]}, status=500)

    STOCK_CHART_CACHE = {}
    def _api_stock_chart(self, u):
        q = urllib.parse.parse_qs(u.query)
        market = self._market(q)
        code = (q.get('code', [''])[0] or '').strip()
        range_ = q.get('range', ['3mo'])[0]
        if not code:
            return self._send_json({'error': 'code required'}, status=400)
        # KR: 6자리 / ^index / =X / US: 알파벳 ticker
        if not (re.match(r'^[A-Z]{1,5}(-[A-Z])?$', code) or
                re.match(r'^\d{6}$', code) or
                code.startswith('^') or code.endswith('=X')):
            return self._send_json({'error': 'invalid code format'}, status=400)
        key = f'{market.id}|{code}|{range_}'
        now = time.time()
        c = Handler.STOCK_CHART_CACHE.get(key)
        if c and (now - c[0]) < 600:
            return self._send_json(c[1])
        try:
            data = fetch_stock_chart(code, range_, market)
            Handler.STOCK_CHART_CACHE[key] = (now, data)
            self._send_json(data)
        except Exception as e:
            self._send_json({'error': str(e)[:200]}, status=500)

    SWEEP_CACHE = {}
    NEWS_SNAPSHOT = {}      # code → 분류·한줄평 완료된 전체 기사 (모달이 DB처럼 읽음)
    SWEEP_LOCK = __import__('threading').Lock()
    SNAP_DIR = os.path.join(ROOT, 'data', 'snapshots')

    @classmethod
    def _save_snapshot(cls, key, data, news=None):
        """sweep 결과(+종목별 뉴스)를 디스크에 영속 — 부팅 시 즉시 로드해 콜드스타트 제거."""
        try:
            os.makedirs(cls.SNAP_DIR, exist_ok=True)
            fn = key.replace('|', '_') + '.json'
            tmp = os.path.join(cls.SNAP_DIR, fn + '.tmp')
            with open(tmp, 'w') as f:
                json.dump({'key': key, 'ts': time.time(), 'data': data, 'news': news or {}}, f, ensure_ascii=False)
            os.replace(tmp, os.path.join(cls.SNAP_DIR, fn))
        except Exception as e:
            print(f'[Snapshot] save {key} 실패: {e}')

    SEED_DIR = os.path.join(ROOT, 'seed')   # repo 에 커밋되는 시드 (Render 재배포 후 즉시 서빙용)

    @classmethod
    def load_snapshots(cls):
        """스냅샷을 메모리 캐시로 로드 — 부팅 직후 즉시 서빙(콜드스타트 제거).
           seed/(커밋됨) 먼저 → data/snapshots/(런타임, 더 신선) 가 덮어씀."""
        n = 0
        for d in (cls.SEED_DIR, cls.SNAP_DIR):
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if not fn.endswith('.json'):
                    continue
                try:
                    with open(os.path.join(d, fn)) as f:
                        obj = json.load(f)
                    key = obj.get('key') or fn[:-5].replace('_', '|', 1)
                    prev = cls.SWEEP_CACHE.get(key)
                    # 더 신선한 것만 유지 (런타임이 시드보다 최신이면 유지)
                    if prev and prev.get('ts', 0) >= obj.get('ts', 0):
                        continue
                    cls.SWEEP_CACHE[key] = {'ts': obj.get('ts', 0), 'data': obj['data'], 'computing': False}
                    news = obj.get('news') or {}
                    if news:
                        cls.NEWS_SNAPSHOT.update(news)   # 종목별 뉴스 DB 복원
                    n += 1
                except Exception:
                    continue
        if n:
            print(f'[Snapshot] {n}개 로드 — 콜드스타트 없이 즉시 서빙')
        return n

    @classmethod
    def _compute_sweep_bg(cls, key, top_n, market):
        """백그라운드 sweep 계산 — HTTP 요청을 블로킹하지 않음. 완료 시 디스크 저장."""
        import time as _t
        try:
            data = fetch_sweep(top_n=top_n, market=market)
            news = data.pop('_stock_news', {})      # 종목별 뉴스 분리 → DB, 클라 응답엔 제외
            cls.SWEEP_CACHE[key] = {'ts': _t.time(), 'data': data, 'computing': False}
            if news:
                cls.NEWS_SNAPSHOT.update(news)
            cls._save_snapshot(key, data, news)
            print(f'[Sweep] {key} 계산 완료 ({data.get("count")}종목, 뉴스 {len(news)}종목)')
        except Exception as e:
            slot = cls.SWEEP_CACHE.get(key)
            if slot:
                slot['computing'] = False
            print(f'[Sweep] {key} 계산 실패: {e}')

    def _api_sweep(self, u):
        q = urllib.parse.parse_qs(u.query)
        market = self._market(q)
        force = q.get('force', ['0'])[0] == '1'
        top_n = int(q.get('top_n', ['120'])[0])
        key = f'{market.id}|{top_n}'
        now = time.time()
        slot = Handler.SWEEP_CACHE.setdefault(key, {'ts': 0, 'data': None, 'computing': False})
        # 신선한 캐시 → 즉시 반환
        if not force and slot['data'] and (now - slot['ts']) < 3600:
            return self._send_json({'cached': True, 'cached_age_sec': int(now - slot['ts']), **slot['data']})
        # 캐시 없음 → 블로킹하지 않고 백그라운드 계산 시작 + 즉시 '준비 중'(503) 응답.
        # 프론트가 폴링하다 완료되면 위 분기에서 데이터 수신. (콜드스타트 멈춤·타임아웃 방지)
        with Handler.SWEEP_LOCK:
            if not slot.get('computing'):
                slot['computing'] = True
                import threading
                threading.Thread(target=Handler._compute_sweep_bg,
                                 args=(key, top_n, market), daemon=True).start()
        # 오래된 데이터라도 있으면 그걸 주고(stale-while-revalidate), 없으면 503
        if slot['data']:
            return self._send_json({'cached': True, 'stale': True, 'cached_age_sec': int(now - slot['ts']), **slot['data']})
        return self._send_json({'computing': True, 'retry_after': 4}, status=503)

    RECENT_PICKS_CACHE = {}
    def _api_recent_picks(self, u):
        q = urllib.parse.parse_qs(u.query)
        market = self._market(q)
        top_n = int(q.get('top_n', ['120'])[0])
        force = q.get('force', ['0'])[0] == '1'
        key = f'{market.id}|{top_n}'
        now = time.time()
        slot = Handler.RECENT_PICKS_CACHE.setdefault(key, {'ts': 0, 'data': None, 'computing': False})
        if not force and slot['data'] and (now - slot['ts']) < 86400:
            self._send_json({'cached': True, 'cached_age_sec': int(now - slot['ts']), **slot['data']})
            return
        if slot['computing'] and slot['data']:
            self._send_json({'cached': True, 'cached_age_sec': int(now - slot['ts']), **slot['data']})
            return
        slot['computing'] = True
        try:
            data = fetch_recent_picks(top_n=top_n, market=market)
            Handler.RECENT_PICKS_CACHE[key] = {'ts': now, 'data': data, 'computing': False}
            self._send_json({'cached': False, **data})
        except Exception as e:
            slot['computing'] = False
            self._send_json({'error': str(e)[:200]}, status=500)

    MACRO_CACHE = {}
    def _api_macro(self, u):
        """거시·지정학 stress + regime 분석. 30분 캐시."""
        q = urllib.parse.parse_qs(u.query)
        market = self._market(q)
        force = q.get('force', ['0'])[0] == '1'
        key = market.id
        now = time.time()
        c = Handler.MACRO_CACHE.get(key)
        if c and not force and (now - c[0]) < 1800:
            return self._send_json({'cached': True, 'cached_age_sec': int(now - c[0]), **c[1]})
        try:
            # 1. 거시 카테고리 articles 만 추출
            news = fetch_news([], 400, market)
            macro_cat_names = {'거시·지정학', 'Macro·Geopolitics'}
            macro_arts = [a for a in news.get('articles', [])
                          if a.get('category') in macro_cat_names]
            # 2. VIX / 유가 fetch
            vix_now = vix_5d_chg = oil_5d_chg = None
            try:
                vix_chart = fetch_stock_chart('^VIX', '1mo', market)
                vb = vix_chart.get('bars', [])
                if vb:
                    vix_now = vb[-1]['c']
                    if len(vb) >= 6:
                        vix_5d_chg = (vb[-1]['c'] - vb[-6]['c']) / vb[-6]['c'] * 100
            except Exception:
                pass
            try:
                # WTI futures = CL=F, Brent = BZ=F
                oil_chart = fetch_stock_chart('CL=F', '1mo', market)
                ob = oil_chart.get('bars', [])
                if ob and len(ob) >= 6:
                    oil_5d_chg = (ob[-1]['c'] - ob[-6]['c']) / ob[-6]['c'] * 100
            except Exception:
                pass
            stress = compute_macro_stress(
                macro_arts, vix_now=vix_now, vix_5d_chg=vix_5d_chg, oil_5d_chg=oil_5d_chg,
            )
            data = {
                'ts': int(now * 1000),
                'market': market.id,
                'macro_news_count': len(macro_arts),
                **stress,
            }
            Handler.MACRO_CACHE[key] = (now, data)
            self._send_json({'cached': False, **data})
        except Exception as e:
            import traceback
            self._send_json({'error': str(e)[:200], 'trace': traceback.format_exc()[-300:]}, status=500)

    WF_CACHE = {}
    def _api_walkforward(self, u):
        q = urllib.parse.parse_qs(u.query)
        market = self._market(q)
        top_n = int(q.get('top_n', ['80'])[0])
        days = int(q.get('days', ['120'])[0])
        top_k = int(q.get('top_k', ['8'])[0])
        hold = int(q.get('hold', ['5'])[0])
        mode = q.get('mode', ['blend'])[0]
        if mode not in ('blend', 'price_only', 'news_only', 'attention', 'attn_blend',
                        'substantive', 'informational', 'regime_polarity'):
            mode = 'blend'
        universe_mode = q.get('universe_mode', ['current'])[0]
        if universe_mode not in ('current', 'kospi200', 'dynamic'):
            universe_mode = 'current'
        use_news = q.get('use_news', ['1'])[0] != '0'
        force = q.get('force', ['0'])[0] == '1'
        cat_filter_raw = q.get('cat_filter', [''])[0]
        cat_filter = tuple(c.strip() for c in cat_filter_raw.split(',') if c.strip()) if cat_filter_raw else ()
        start_offset_days = int(q.get('start_offset_days', ['0'])[0])
        start_offset_days = max(0, min(360, start_offset_days))
        key = f'{market.id}|{top_n}|{days}|{top_k}|{hold}|{mode}|{use_news}|{universe_mode}|{",".join(cat_filter)}|{start_offset_days}'
        now = time.time()
        slot = Handler.WF_CACHE.setdefault(key, {'ts': 0, 'data': None, 'computing': False})
        if not force and slot['data'] and (now - slot['ts']) < 86400:
            self._send_json({'cached': True, 'cached_age_sec': int(now - slot['ts']), **slot['data']})
            return
        if slot['computing'] and slot['data']:
            self._send_json({'cached': True, 'cached_age_sec': int(now - slot['ts']), **slot['data']})
            return
        slot['computing'] = True
        try:
            data = walkforward_backtest(
                market=market, top_n=top_n, days=days, top_k=top_k, hold=hold,
                use_news=use_news, mode=mode, universe_mode=universe_mode,
                cat_filter=cat_filter, start_offset_days=start_offset_days,
            )
            Handler.WF_CACHE[key] = {'ts': now, 'data': data, 'computing': False}
            self._send_json({'cached': False, **data})
        except Exception as e:
            slot['computing'] = False
            import traceback
            self._send_json({'error': str(e)[:200], 'trace': traceback.format_exc()[-400:]}, status=500)
