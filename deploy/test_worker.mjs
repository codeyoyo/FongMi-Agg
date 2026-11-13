import worker from './worker.js';
import fs from 'fs';
const ASSETS = {
  async fetch(req) {
    const u = req instanceof URL ? req : new URL(req.url);
    const p = 'dist2' + u.pathname;
    if (!fs.existsSync(p)) return new Response('not found', {status: 404});
    return new Response(fs.readFileSync(p), {headers: {'content-type': 'application/json'}});
  }
};
for (const [path, expect] of [['/fongmi.json','clean'],['/fongmi.json?mode=full','full'],['/fongmi.json?mode=clean','clean']]) {
  const r = await worker.fetch(new Request('http://x' + path), {ASSETS});
  const j = JSON.parse(await r.text());
  const http = j.sites.filter(s => String(s.api||'').startsWith('http')).length;
  console.log(`${path.padEnd(26)} -> ${r.headers.get('x-config-mode')}  sites=${j.sites.length} http=${http}  ${r.headers.get('x-config-mode')===expect?'✓':'✗ 期望'+expect}`);
}
