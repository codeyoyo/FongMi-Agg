// _worker.js —— Pages advanced mode
//
// 两份"组"配置（FongMi sites 里只有两条，每条内部聚合几十个源）：
//   /other                       → 「其它」聚合站（TVBox 采集站协议）
//   /adult                       → 「成人资源」聚合站
// 两种站点类型都是 type:1（纯 HTTP），FongMi 直接支持，设备端不需要装任何模块。
//
// 聚合协议（与 TVBox 采集站一致）：
//   ?ac=list                       → 合并后的分类表
//   ?ac=videolist&t=<桶名>&pg=1     → 该分类下所有源第 pg 页合并
//   ?ac=detail&ids=s<源序>|<vod_id> → 详情/播放地址
//   ?wd=<关键词>&ac=videolist       → 全源聚合搜索
//
// 旧入口保留：/fongmi.json 默认 clean，?mode=other|adult|full|basic

const TIMEOUT_MS = 4000;
const BATCH = 6;
const CACHE_SECONDS = 300;
const UA = 'Mozilla/5.0 (Linux; Android 12)';

const STATS = [];

// 默认 clean —— 原来的口径：sites 直接是各采集站 / js 源，FongMi 原生对接
const MODE_MAP = {
  full: '/full.json',
  two: '/two.json',
  clean: '/clean.json',
  basic: '/basic.json',
  other: '/other.json',
  adult: '/adult.json',
};

// ---------- 基础工具 ----------

function json(obj, status = 200, extra = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': `public, max-age=${CACHE_SECONDS}`,
      'access-control-allow-origin': '*',
      ...extra,
    },
  });
}

function joinApi(api, query) {
  // 有些源地址自带 ?ac=list，必须把旧 query 剥掉再拼，否则 ac 参数重复
  const base = api.split('?')[0];
  return base + (base.includes('?') ? '&' : '?') + query;
}

// Cloudflare 每请求的子请求并发有限，串行分批比一次性 Promise.all 更稳
async function runBatched(factories) {
  const out = [];
  for (let i = 0; i < factories.length; i += BATCH) {
    const part = await Promise.all(factories.slice(i, i + BATCH).map((f) => f()));
    out.push(...part);
  }
  return out;
}

async function fetchText(url, type) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      signal: ctl.signal,
      headers: { 'User-Agent': UA, Accept: '*/*' },
      cf: { cacheTtl: CACHE_SECONDS, cacheEverything: true },
    });
    if (!res.ok) return null;
    return await res.text();
  } catch (e) {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function txt(x) {
  if (x == null) return '';
  return String(x)
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1')
    .replace(/<[^>]+>/g, '')
    .trim();
}

function parseXmlVideos(body) {
  const out = [];
  const re = /<video>([\s\S]*?)<\/video>/g;
  let m;
  while ((m = re.exec(body))) {
    const seg = m[1];
    const get = (tag) => {
      const r = new RegExp('<' + tag + '[^>]*>([\\s\\S]*?)<\\/' + tag + '>').exec(seg);
      return r ? txt(r[1]) : '';
    };
    // XML 站的播放地址在 <dl><dd flag="线路名">名$地址#名$地址</dd></dl> 里，
    // 不是 JSON 风格的 <vod_play_url>；不解析这里，所有 type=0 站点的播放都是空的。
    let xFrom = '';
    let xUrl = '';
    const dl = /<dl>([\s\S]*?)<\/dl>/.exec(seg);
    if (dl) {
      const fs = [];
      const us = [];
      const reDd = /<dd([^>]*)>([\s\S]*?)<\/dd>/g;
      let d;
      let n = 0;
      while ((d = reDd.exec(dl[1]))) {
        const body = txt(d[2]);
        if (!body) continue;
        const fm = /flag="([^"]*)"/.exec(d[1]);
        n += 1;
        fs.push((fm && fm[1].trim()) || '线路' + n);
        us.push(body);
      }
      xFrom = fs.join('$$$');
      xUrl = us.join('$$$');
    }
    out.push({
      vod_id: get('id'),
      vod_name: get('name'),
      vod_pic: get('pic'),
      vod_remarks: get('note') || get('last'),
      vod_year: get('year'),
      vod_area: get('area'),
      vod_actor: get('actor'),
      vod_director: get('director'),
      type_name: get('type'),
      vod_content: get('des'),
      vod_play_from: xFrom,
      vod_play_url: xUrl,
    });
  }
  return out;
}

function parseXmlClasses(body) {
  const out = [];
  const seg = /<class>([\s\S]*?)<\/class>/.exec(body);
  const text = seg ? seg[1] : body;
  const re = /<ty\s+id="([^"]+)"\s*>([\s\S]*?)<\/ty>/g;
  let m;
  while ((m = re.exec(text))) out.push({ type_id: m[1].trim(), type_name: txt(m[2]) });
  return out;
}

async function pull(src, query) {
  const q = src.type === 0 ? query + '&at=xml' : query;
  const body = await fetchText(joinApi(src.api, q), src.type);
  if (!body) return null;
  if (src.type === 0 || body.trim().startsWith('<')) {
    return { kind: 'xml', body };
  }
  try {
    return { kind: 'json', data: JSON.parse(body) };
  } catch (e) {
    return null;
  }
}

// 播放地址健康检查：m3u8 能读到 #EXTM3U 才算活，403/落地页一律判死
async function lineOk(url) {
  if (!/^https?:\/\//.test(String(url || ''))) return false;
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 2000);
  try {
    const res = await fetch(url, {
      signal: ctl.signal,
      headers: { 'User-Agent': UA, Range: 'bytes=0-2047', Accept: '*/*' },
    });
    if (!res.ok) return false;
    const text = await res.text();
    const head = text.slice(0, 512).replace(/^\s+/, '');
    return head.startsWith('#EXTM3U') || head.startsWith('#EXTINF') || head.startsWith('#EXT-X');
  } catch (e) {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

// ---------- 组数据 ----------

async function loadGroup(env, origin, group) {
  const res = await env.ASSETS.fetch(new URL('/agg_srcs.json', origin));
  if (!res.ok) return null;
  const all = await res.json();
  return all[group] || null;
}

const BUCKET_KWS = [
  ['电影', ['电影', '片']],
  ['电视剧', ['电视剧', '连续剧', '剧集', '剧']],
  ['综艺', ['综艺']],
  ['动漫', ['动漫', '动画']],
  ['纪录片', ['纪录']],
];

function bucketOf(name) {
  const n = String(name || '');
  for (const [b, kws] of BUCKET_KWS) {
    for (const k of kws) if (n.includes(k)) return b;
  }
  return '其它';
}

// 同一组里去重后的源列表；idx 必须全局一致（vod_id 里的 s<idx> 靠它还原）
function uniqueSrcs(g) {
  const seen = new Set();
  const out = [];
  for (const b of g.buckets || []) {
    for (const s of b.srcs || []) {
      if (seen.has(s.api)) continue;
      seen.add(s.api);
      out.push(s);
    }
  }
  return out;
}

function bucketByName(g, name) {
  return (g.buckets || []).find((b) => b.name === name) || null;
}


function pageHtml(group, items, extra) {
  const title = group === 'adult' ? '成人资源' : '其它';
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const cards = items.map((x) => `
    <a class="c" href="${esc(x.vod_pic || '')}" target="_blank" rel="noreferrer">
      <img loading="lazy" src="${esc(x.vod_pic || '')}" alt="">
      <div class="m"><b>${esc(x.vod_name)}</b><span>${esc(x.type_name || '')} ${esc(x.vod_remarks || '')}</span><em>${esc(x._src || '')}</em></div>
    </a>`).join('');
  const nav = ['other', 'adult'].map((g) => `<a class="${g === group ? 'on' : ''}" href="/preview?g=${g}">${g === 'adult' ? '成人资源' : '其它'}</a>`).join('');
  const cats = ['全部', '电影', '电视剧', '综艺', '动漫', '纪录片'].map((c) => `<a class="${c === extra.cat ? 'on' : ''}" href="/preview?g=${group}&t=${encodeURIComponent(c)}">${c}</a>`).join('');
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title} · 聚合预览</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#111;color:#e6e6e6;font:14px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;background:#181818;padding:10px 12px;border-bottom:1px solid #262626;z-index:2}
h1{margin:0 0 8px;font-size:16px;font-weight:600}
h1 small{color:#888;font-weight:400;margin-left:8px}
nav.cats{display:flex;gap:6px;overflow:auto;padding-bottom:2px}
nav.cats a,nav.cats a:visited{flex:0 0 auto;padding:5px 12px;border-radius:999px;background:#222;color:#bbb;text-decoration:none;font-size:13px}
nav.cats a.on{background:#2b6cb0;color:#fff}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(108px,1fr));gap:10px;padding:12px}
.c{text-decoration:none;color:inherit}
.c img{width:100%;aspect-ratio:2/3;object-fit:cover;border-radius:6px;background:#222;display:block}
.m b{display:block;font-size:13px;margin-top:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.m span,.m em{display:block;font-size:11px;color:#8a8a8a;font-style:normal;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
footer{padding:16px 12px 40px;color:#666;font-size:12px}
</style></head><body>
<header><h1>${title} <small>${extra.n} 个源聚合 · 第 1 页 ${items.length} 条</small></h1>
<nav class="cats">${cats}</nav></header>
<div class="grid">${cards || '<p style="padding:12px;color:#888">这一页没有拉到内容，换页或稍后再试。</p>'}</div>
<footer>这是网页预览，用来确认聚合是否正常。FongMi 里粘贴的地址是 <code>https://fm.le138.de5.net/fongmi.json</code>。</footer>
</body></html>`;
}

// ---------- 三种协议 ----------

async function handleList(g) {
  const classes = [{ type_id: '全部', type_name: '全部' }].concat(
    (g.buckets || []).map((b) => ({ type_id: b.name, type_name: b.name }))
  );
  return json({ class: classes, filters: {} });
}

const MAX_ITEMS = 80;

// 轮询交错：各源轮流各出一条，避免被某个片库最大的站整页淹没
function interleave(groups) {
  const out = [];
  const seen = new Set();
  const cursor = groups.map(() => 0);
  let added = true;
  while (added && out.length < MAX_ITEMS) {
    added = false;
    groups.forEach((g, i) => {
      if (!g || out.length >= MAX_ITEMS) return;
      while (cursor[i] < g.items.length) {
        const it = g.items[cursor[i]++];
        if (!it) continue;
        const name = String(it.vod_name || '').trim();
        if (!name || seen.has(name)) continue;
        seen.add(name);
        out.push({ ...it, vod_id: `s${g.idx}|${it.vod_id}` });
        added = true;
        return;
      }
    });
  }
  return out;
}

function mergeList(items, idx) {
  return (items || []).map((it) => ({ ...it, vod_id: `s${idx}|${it.vod_id}` }));
}

async function handleCategory(g, bucketName, pg) {
  const all = uniqueSrcs(g);
  // vod_id 里的 s<idx> 靠 uniqueSrcs 的顺序还原，所以全局下标必须由它决定
  const idxOf = new Map();
  all.forEach((s, i) => idxOf.set(s.api, i));

  const wantAll = bucketName === '全部';
  const bucket = wantAll ? null : (g.buckets || []).find((b) => b.name === bucketName);
  // 分类聚合的正确姿势：每个源用它自己站点里这个分类的 tid 去拉，
  // 而不是拉站点首页再本地过滤（一页 20 条里常常只有 2-3 条属于该分类）
  const srcs = bucket ? bucket.srcs : all;

  const tasks = srcs.map((src) => async () => {
    const t0 = Date.now();
    const idx = idxOf.has(src.api) ? idxOf.get(src.api) : -1;
    // 构建期已探测过每个源在这类目下认不认 t=，直接用记好的模板，运行时零试错
    const q = !wantAll && src.q ? String(src.q).replace('{pg}', pg) : `ac=videolist&pg=${pg}`;
    const r = await pull(src, q);
    if (!r) {
      STATS.push({ i: idx, n: -1, ms: Date.now() - t0, name: src.name });
      return null;
    }
    let items = [];
    let pc = 1;
    if (r.kind === 'xml') {
      items = parseXmlVideos(r.body);
      pc = 1;
    } else {
      items = Array.isArray(r.data && r.data.list) ? r.data.list : [];
      const total = Number(r.data && r.data.total) || 0;
      pc = Number(r.data && r.data.pagecount) || (total ? Math.ceil(total / 20) : 1);
    }
    let final = items;
    if (!wantAll) {
      const byType = items.filter((it) => bucketOf(it.type_name) === bucketName);
      // 站内 tid 生效时结果本就该全是该类；过滤后为空说明它忽略了 t，退回原列表
      final = src.tid && byType.length === 0 ? items : byType;
    }
    STATS.push({ i: idx, n: items.length, hit: final.length, ms: Date.now() - t0, name: src.name, tid: src.tid || null, pc });
    return { idx, items: final, pagecount: pc };
  });

  const results = await runBatched(tasks);
  const stats = STATS.splice(0, STATS.length);
  // 各源自报的页数差异极大（几十到上万），取中位数，别让单个站把总页数顶到 6000
  const pcs = results.filter((r) => r && r.pagecount > 0).map((r) => r.pagecount).sort((a, b) => a - b);
  const pagecount = pcs.length ? pcs[Math.floor(pcs.length / 2)] : 1;
  const items = interleave(results.map((r) => (r ? { idx: r.idx, items: r.items || [] } : null)));
  const body = { list: items, page: pg, pagecount, limit: items.length, total: pagecount * items.length };
  if (new URL(globalThis.__requrl || 'http://x').searchParams.get('debug')) body.debug = stats;
  return json(body);
}

async function handleDetail(g, ids) {
  const want = String(ids).split(',').filter(Boolean);
  const all = uniqueSrcs(g);
  const out = [];

  // 1) 先按 vod_id 里的源序号取原始详情
  const bySrc = new Map();
  for (const raw of want) {
    const m = /^s(\d+)\|(.*)$/.exec(raw);
    if (!m) continue;
    const idx = Number(m[1]);
    if (!bySrc.has(idx)) bySrc.set(idx, []);
    bySrc.get(idx).push({ raw, vid: m[2] });
  }

  const primary = [];
  for (const [idx, arr] of bySrc) {
    const src = all[idx];
    if (!src) continue;
    const r = await pull(src, `ac=detail&ids=${encodeURIComponent(arr.map((x) => x.vid).join(','))}`);
    if (!r) continue;
    let list = [];
    if (r.kind === 'xml') list = parseXmlVideos(r.body);
    else list = (r.data && r.data.list) || [];
    for (const it of list) primary.push({ ...it, _idx: idx });
  }
  if (!primary.length) return json({ list: [] });

  // 2) 同一部片去其他源找同名，把它们的播放线路并成一排。
  //    单条线路挂了还能换，这才是"聚合"该给的东西。
  //    不能用"前 N 个源"抽样：排在前面的源可能整批不支持搜索，
  //    实测就因此把 15 条线路缩成 1 条。改成全量搜索 + 只对命中源拉详情。
  const extras = await Promise.all(
    primary.map(async (it) => {
      const name = String(it.vod_name || '').trim();
      if (!name) return [];
      const others = all.map((s, i) => ({ s, i })).filter(({ i }) => i !== it._idx);

      // 阶段一：并发搜索，只留真正命中同名的
      const hits = await runBatched(
        others.map(({ s, i }) => async () => {
          const r = await pull(s, `wd=${encodeURIComponent(name)}&ac=videolist&pg=1`);
          if (!r) return null;
          const items = r.kind === 'xml' ? parseXmlVideos(r.body) : (r.data && r.data.list) || [];
          const hit = items.find((x) => String(x.vod_name || '').trim() === name);
          return hit ? { s, vid: hit.vod_id } : null;
        })
      );

      // 阶段二：只对命中的源拉详情取 play_url
      const valid = hits.filter(Boolean);
      const got = await runBatched(
        valid.map((h) => async () => {
          const d = await pull(h.s, `ac=detail&ids=${encodeURIComponent(h.vid)}`);
          if (!d) return null;
          const dl = d.kind === 'xml' ? parseXmlVideos(d.body) : (d.data && d.data.list) || [];
          const one = dl[0];
          if (!one || !one.vod_play_url) return null;
          return { from: String(one.vod_play_from || h.s.name).trim() || h.s.name, url: one.vod_play_url };
        })
      );
      return got.filter(Boolean);
    })
  );

  // 逐条线路探活：能播的排前面，死线路丢到后面兜底
  const probed = await Promise.all(
    primary.map(async (it, i) => {
      const lines = [{ from: String(it.vod_play_from || '线路1').trim(), url: it.vod_play_url }].concat(extras[i] || []);
      const uniqLines = [];
      const seenFrom = new Set();
      for (const l of lines) {
        if (!l.url || seenFrom.has(l.from)) continue;
        seenFrom.add(l.from);
        uniqLines.push(l);
      }
      // 只探前 4 条：够用户切了，全探会把详情拖到十秒
      const head = uniqLines.slice(0, 4);
      const tail = uniqLines.slice(4).map((l) => ({ ...l, ok: false }));
      const checks = await runBatched(
        head.map((l) => async () => {
          const first = String(l.url).split('#')[0].split('$').pop();
          return { ...l, ok: await lineOk(first) };
        })
      );
      const good = checks.filter((x) => x.ok);
      const bad = checks.filter((x) => !x.ok);
      return { it, i, lines: good.concat(bad).concat(tail) };
    })
  );

  probed.forEach(({ it, lines }) => {
    const uniq = lines;
    out.push({
      ...it,
      vod_play_from: uniq.map((l) => l.from).join('$$$'),
      vod_play_url: uniq.map((l) => l.url).join('$$$'),
      vod_id: `s${it._idx}|${it.vod_id}`,
    });
  });

  return json({ list: out });
}

async function handleSearch(g, wd, pg) {
  // 全源串行分批太慢（25 源 ≈ 10s），搜索只打片库最大的前 15 个
  const uniq = uniqueSrcs(g).slice(0, 15);
  const results = await runBatched(
    uniq.map((src, idx) => async () => {
      const r = await pull(src, `wd=${encodeURIComponent(wd)}&ac=videolist&pg=${pg}`);
      if (!r) return null;
      const items = r.kind === 'xml' ? parseXmlVideos(r.body) : (r.data && r.data.list) || [];
      return { idx, items };
    })
  );
  let items = [];
  for (const r of results) {
    if (!r) continue;
    items = items.concat(mergeList(r.items, r.idx, 0));
  }
  return json({ list: items, page: pg, pagecount: 1, limit: items.length, total: items.length });
}

// ---------- 入口 ----------

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    globalThis.__requrl = request.url;
    const path = url.pathname;

    if (path === '/fongmi.json' || path === '/') {
      const mode = (url.searchParams.get('mode') || 'two').toLowerCase();
      const target = MODE_MAP[mode] || '/two.json';
      const res = await env.ASSETS.fetch(new URL(target, url.origin));
      if (!res.ok) return json({ error: 'config missing', target }, 500);
      return new Response(await res.text(), {
        headers: {
          'content-type': 'application/json; charset=utf-8',
          'cache-control': 'no-cache, must-revalidate',
          'access-control-allow-origin': '*',
          'x-config-mode': MODE_MAP[mode] ? mode : 'two',
        },
      });
    }

    if (path === '/probe') {
      // 调试用：?u=<编码后的源地址>&q=<查询串>，返回状态码/耗时/前 160 字符
      const target = url.searchParams.get('u') || '';
      const q = url.searchParams.get('q') || 'ac=videolist&pg=1';
      if (!/^https?:\/\//.test(target)) return json({ error: 'bad url' }, 400);
      const t0 = Date.now();
      const body = await fetchText(joinApi(target, q), 1);
      return json({
        url: joinApi(target, q),
        ms: Date.now() - t0,
        ok: !!body,
        head: body ? body.slice(0, 160) : null,
      });
    }

    if (path === '/preview') {
      const group = url.searchParams.get('g') === 'adult' ? 'adult' : 'other';
      const g = await loadGroup(env, url.origin, group);
      if (!g) return new Response('agg_srcs.json 缺失', { status: 500 });
      const cat = url.searchParams.get('t') || '全部';
      const srcs = uniqueSrcs(g);
      const body = await handleCategory(g, cat, 1);
      const data = await body.json();
      const list = (data.list || []).map((x) => {
        const idx = Number(String(x.vod_id).split('|')[0].slice(1));
        const src = srcs[idx];
        return { ...x, _src: src ? src.name : '' };
      });
      return new Response(pageHtml(group, list, { n: srcs.length, cat }), {
        headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'public, max-age=120' },
      });
    }

    if (path === '/other' || path === '/adult') {
      // 浏览器直接点开时不要糊一脸 JSON，跳去网页预览
      const accept = request.headers.get('Accept') || '';
      if (!url.searchParams.get('ac') && !url.searchParams.get('wd') && accept.includes('text/html')) {
        return Response.redirect(url.origin + '/preview?g=' + (path === '/adult' ? 'adult' : 'other'), 302);
      }
      const group = path === '/adult' ? 'adult' : 'other';
      const g = await loadGroup(env, url.origin, group);
      if (!g) return json({ list: [] }, 500);

      const ac = (url.searchParams.get('ac') || '').toLowerCase();
      const wd = url.searchParams.get('wd');
      const ids = url.searchParams.get('ids') || '';
      const pg = Math.max(1, parseInt(url.searchParams.get('pg') || '1', 10) || 1);

      // FongMi 对 type=1 站点的真实调用（app/.../api/SiteApi.java）：
      //   首页      GET api                    —— 无任何参数，期望分类表
      //   分类列表  ac=detail&t=<分类>&pg=<页>  —— 注意 ac 就是 detail，且没有 ids
      //   详情      ac=detail&ids=<id>
      //   搜索      wd=&quick=&extend=          —— 没有 ac
      // 所以形态只能靠 ids / t / wd 判定；用 ac 当主依据会把分类请求吞成空详情。
      if (wd) return handleSearch(g, wd, pg);
      if (ids) return handleDetail(g, ids);
      const t = url.searchParams.get('t');
      if (t) return handleCategory(g, t, pg);
      return handleList(g);
    }

    return env.ASSETS.fetch(request);
  },
};
