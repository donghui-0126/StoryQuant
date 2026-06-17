"""StoryQuant 서버 부팅."""
import socketserver
import sys
import threading
import time

from .api import Handler
from .markets import get_market, list_markets


def load_universes():
    """모든 등록된 시장의 universe 부팅 시 백그라운드 로드."""
    for mid in list_markets():
        m = get_market(mid)
        try:
            u = m.load_universe(top_per_market=200)
            print(f'[Universe:{mid}] loaded {len(u)} tickers')
        except Exception as e:
            print(f'[Universe:{mid}] load failed: {e}')


def refresh_loop():
    """주기적 sweep 갱신 — 백엔드가 '시간마다 폴링·저장', 클라는 읽기만.
       부팅 시 디스크/시드 스냅샷을 먼저 로드(즉시 서빙)한 뒤, 백그라운드로 라이브 갱신.
       env: SWEEP_WARM=0(끄기) · SWEEP_WARM_N(종목 수) · SWEEP_REFRESH_MIN(주기, 기본 30)."""
    import os
    Handler.load_snapshots()                 # 디스크/시드 즉시 로드 → 콜드스타트 없음
    if os.environ.get('SWEEP_WARM') == '0':
        print('[Refresh] disabled (SWEEP_WARM=0) — 시드 스냅샷만 서빙')
        return
    top_n = int(os.environ.get('SWEEP_WARM_N', 80))
    period = int(os.environ.get('SWEEP_REFRESH_MIN', 30)) * 60
    key = f'kr|{top_n}'
    from .core.strategy import fetch_sweep
    m = get_market('kr')
    time.sleep(8)                            # universe 로드 먼저
    while True:
        try:
            t0 = time.time()
            data = fetch_sweep(top_n=top_n, market=m)
            news = data.pop('_stock_news', {})       # 종목별 뉴스 → DB(NEWS_SNAPSHOT), 클라 응답엔 제외
            Handler.SWEEP_CACHE[key] = {'ts': time.time(), 'data': data, 'computing': False}
            if news:
                Handler.NEWS_SNAPSHOT.update(news)
            Handler._save_snapshot(key, data, news)
            print(f'[Refresh] {key} 갱신·저장 ({int(time.time()-t0)}s, 뉴스 {len(news)}종목)')
        except Exception as e:
            print(f'[Refresh] {key} 실패: {e}')
        time.sleep(period)


def warm_universe():
    """universe 전체 종목 뉴스를 백그라운드로 미리 분류·한줄평 → NEWS_SNAPSHOT(DB).
       검색으로 어떤 종목을 눌러도 콜드 LLM 없이 즉시 뜨도록.
       env: WARM_UNIVERSE=0(끄기) · WARM_UNIVERSE_N(상한) · WARM_UNIVERSE_PAGE(종목당 건수)."""
    import os
    if os.environ.get('WARM_UNIVERSE') == '0' or os.environ.get('SWEEP_WARM') == '0':
        return
    limit = int(os.environ.get('WARM_UNIVERSE_N', 9999))
    page_size = int(os.environ.get('WARM_UNIVERSE_PAGE', 20))
    period = int(os.environ.get('SWEEP_REFRESH_MIN', 30)) * 60
    from .core.news import fetch_stock_news
    m = get_market('kr')
    time.sleep(45)   # 피드 워밍(refresh_loop) 먼저 끝나도록 양보
    while True:
        try:
            codes = list(m.universe().keys())[:limit]
            done = 0
            t0 = time.time()
            for i, code in enumerate(codes):
                try:
                    news = fetch_stock_news(code, page=1, page_size=page_size,
                                            market=m, use_llm=True, gen_comments=True)
                    arts = news.get('articles') or []
                    if arts:
                        Handler.NEWS_SNAPSHOT[code] = [
                            {'title': a.get('title'), 'link': a.get('link'),
                             'paper': a.get('paper') or a.get('source'), 'ts': a.get('ts'),
                             'sentiment': a.get('sentiment'), 'substance': a.get('substance'),
                             'priced_in': bool(a.get('priced_in')), 'llm_label': a.get('llm_label'),
                             'llm_reason': a.get('llm_reason'), 'llm_comment': a.get('llm_comment'),
                             'category': a.get('category'), 'scope': a.get('scope')}
                            for a in arts]
                        done += 1
                    if (i + 1) % 25 == 0:
                        Handler.save_news_snapshot('kr')   # 주기적 영속
                except Exception:
                    continue
                time.sleep(0.2)   # rate-limit 완화
            Handler.save_news_snapshot('kr')
            print(f'[WarmUniverse] {done}/{len(codes)}종목 뉴스 웜업 완료 ({int(time.time()-t0)}s)')
        except Exception as e:
            print(f'[WarmUniverse] 실패: {e}')
        time.sleep(period)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def run(port=8765, host='127.0.0.1'):
    threading.Thread(target=load_universes, daemon=True).start()
    threading.Thread(target=refresh_loop, daemon=True).start()
    threading.Thread(target=warm_universe, daemon=True).start()
    print(f'StoryQuant server → http://{host}:{port}/shorts.html')
    with _Server((host, port), Handler) as srv:
        srv.serve_forever()


if __name__ == '__main__':
    import os
    # Render 등 PaaS: $PORT 주입 + 0.0.0.0 바인딩. 로컬: argv 또는 8765.
    env_port = os.environ.get('PORT')
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(env_port or 8765)
    host = '0.0.0.0' if env_port else '127.0.0.1'
    run(port=port, host=host)
