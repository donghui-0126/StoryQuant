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


def run(port=8765):
    threading.Thread(target=load_universes, daemon=True).start()
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
