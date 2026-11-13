// worker.js —— 订阅入口，按 ?mode= 返回不同版本
//
//   /fongmi.json               → 干净版（默认，家里电视用）
//   /fongmi.json?mode=clean    → 同上
//   /fongmi.json?mode=full     → 全量（自己用）
//
// 其余路径直接交给静态资源。

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/fongmi.json') {
      const mode = (url.searchParams.get('mode') || 'clean').toLowerCase();
      const target = mode === 'full' ? '/full.json' : '/clean.json';

      const asset = await env.ASSETS.fetch(new URL(target, url.origin));
      if (!asset.ok) {
        return new Response(JSON.stringify({ error: 'config not found', target }), {
          status: 500,
          headers: { 'content-type': 'application/json; charset=utf-8' },
        });
      }
      const body = await asset.text();
      return new Response(body, {
        headers: {
          'content-type': 'application/json; charset=utf-8',
          // 订阅内容每天变，但要让 FongMi 每次拿到最新
          'cache-control': 'no-cache, must-revalidate',
          'access-control-allow-origin': '*',
          'x-config-mode': mode === 'full' ? 'full' : 'clean',
        },
      });
    }

    return env.ASSETS.fetch(request);
  },
};
