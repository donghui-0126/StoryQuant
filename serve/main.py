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
    """기본 sweep(KR top_n) 미리 계산해 캐시 적재 — 첫 사용자 콜드 로딩(~86s) 방지."""
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


def run(port=8765):
    threading.Thread(target=load_universes, daemon=True).start()
    threading.Thread(target=warm_sweep, daemon=True).start()
    print(f'╔══════════════════════════════════════════╗')
    print(f'║  StoryQuant local server                 ║')
    print(f'║  http://127.0.0.1:{port}/story_quant.html ║')
    print(f'║  API: /api/news /quote /universe /sweep  ║')
    print(f'║       /walkforward /recent-picks         ║')
    print(f'║  ?market=kr|us — 다중 시장 지원          ║')
    print(f'╚══════════════════════════════════════════╝')
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(('127.0.0.1', port), Handler) as srv:
        srv.serve_forever()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    run(port=port)
