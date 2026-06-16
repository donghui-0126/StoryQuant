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


def warm_sweep(top_n=200):
    """기본 sweep(KR top_n) 미리 계산해 캐시 적재 — 첫 사용자 콜드 로딩(~86s) 방지.
       SWEEP_WARM=0 이면 비활성 (Render 무료 티어 콜드스타트 LLM 비용 절감용)."""
    import os
    if os.environ.get('SWEEP_WARM') == '0':
        print('[Warm] disabled (SWEEP_WARM=0)')
        return
    top_n = int(os.environ.get('SWEEP_WARM_N', top_n))
    time.sleep(8)   # universe 로드 먼저 끝나도록 대기
    try:
        from .core.strategy import fetch_sweep
        m = get_market('kr')
        t0 = time.time()
        data = fetch_sweep(top_n=top_n, market=m)
        Handler.SWEEP_CACHE[f'kr|{top_n}'] = {'ts': time.time(), 'data': data, 'computing': False}
        print(f'[Warm] kr sweep top_n={top_n} 캐시 적재 ({int(time.time()-t0)}s)')
    except Exception as e:
        print(f'[Warm] sweep 워밍 실패: {e}')


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def run(port=8765, host='127.0.0.1'):
    threading.Thread(target=load_universes, daemon=True).start()
    threading.Thread(target=warm_sweep, daemon=True).start()
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
