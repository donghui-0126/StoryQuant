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


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def run(port=8765, host='127.0.0.1'):
    threading.Thread(target=load_universes, daemon=True).start()
    threading.Thread(target=refresh_loop, daemon=True).start()
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
