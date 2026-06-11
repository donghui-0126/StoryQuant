/* ======================================================================
 *  StoryQuant — Cloudflare Worker (정적 앱 + API 프록시)
 *
 *  고정 주소 1개로 전부 서빙:
 *    /            → shorts.html (정적 asset)
 *    /api/*       → KV(CFG).api_origin 에 저장된 백엔드(터널)로 프록시
 *
 *  백엔드 quick tunnel 주소가 바뀌면 deploy/tunnel-keeper.sh 가
 *  KV 의 api_origin 을 자동 갱신 — 프론트 주소는 절대 안 바뀜.
 *  같은 origin 이므로 CORS·CSP 추가 설정 불필요.
 * ====================================================================== */

export default {
  async fetch(req, env) {
    const url = new URL(req.url);

    if (url.pathname.startsWith('/api/')) {
      const origin = await env.CFG.get('api_origin');
      if (!origin) {
        return new Response(JSON.stringify({ error: 'backend not connected (api_origin 미설정)' }), {
          status: 503, headers: { 'content-type': 'application/json' },
        });
      }
      const target = origin.replace(/\/+$/, '') + url.pathname + url.search;
      try {
        const upstream = await fetch(target, {
          method: req.method,
          headers: { 'accept': 'application/json' },
          body: ['GET', 'HEAD'].includes(req.method) ? undefined : req.body,
        });
        const headers = new Headers();
        headers.set('content-type', upstream.headers.get('content-type') || 'application/json');
        headers.set('cache-control', 'no-store');
        return new Response(upstream.body, { status: upstream.status, headers });
      } catch (e) {
        return new Response(JSON.stringify({ error: 'backend unreachable: ' + (e.message || '') }), {
          status: 502, headers: { 'content-type': 'application/json' },
        });
      }
    }

    return env.ASSETS.fetch(req);
  },
};
