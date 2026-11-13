#!/usr/bin/env python3
"""build.py —— FongMi 订阅聚合：采集 → 解析 → 测活 → 输出
输出：dist/fongmi.json（订阅）、dist/live.m3u（直播源）、dist/stats.json（统计）

用法：
  python3 build.py                    # 用 sources.txt 里的源
  python3 build.py --sites-only       # 只测点播站点
  python3 build.py --lives-only       # 只测直播源
"""
import argparse, concurrent.futures as cf, json, os, re, ssl, sys, time
import urllib.request
from urllib.parse import urljoin

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(BASE, 'dist')
UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE


# ---------- 基础 ----------

def get(url, timeout=10, limit=2 << 20, rng=None, headers=None):
    h = dict(UA); h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    if rng: req.add_header('Range', rng)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.status, r.read(limit), r.headers


def clean(u):
    """去控制字符 + 排除 m3u8 属性续行（如 RESOLUTION=1920x1080）"""
    u = ''.join(ch for ch in (u or '') if ch.isprintable()).strip()
    if not u or u.startswith('#') or ' ' in u: return None
    if '=' in u and '/' not in u: return None
    return u


# ---------- 采集 ----------

def load_sources():
    p = os.path.join(BASE, 'sources.txt')
    if not os.path.exists(p): return []
    out = []
    for line in open(p, encoding='utf-8'):
        line = line.strip()
        if line and not line.startswith('#'): out.append(line)
    return out


def fetch_source(url):
    """拉一个配置，返回 (url, dict|None, err)"""
    try:
        st, body, _ = get(url, timeout=20)
        if st != 200: return (url, None, f'http{st}')
        text = body.decode('utf-8', 'ignore').strip()
        if text.startswith('{'): return (url, json.loads(text), None)
        if '#EXTM3U' in text[:64] or ',#' in text[:2000]:
            return (url, {'_m3u_or_txt': text}, None)
        return (url, None, 'unknown-format')
    except Exception as e:
        return (url, None, f'{type(e).__name__}:{str(e)[:40]}')


# ---------- 点播站点测活 ----------

def probe_site(s, timeout=8):
    api = s.get('api') or ''
    if not api.startswith('http'): return (s, 0, 'non-http')
    url = api + ('&' if '?' in api else '?') + 'ac=list'
    t = time.time()
    try:
        st, body, _ = get(url, timeout=timeout, limit=200000, headers=s.get('header') or {})
        ms = round((time.time() - t) * 1000)
        if st != 200: return (s, 0, f'http{st}')
        text = body.decode('utf-8', 'ignore').strip()
        # 关键：200 也可能是假的，必须校验内容
        if text.startswith('{'):
            j = json.loads(text)
            n = len(j.get('class') or []); pc = j.get('pagecount') or j.get('total') or 0
            if n == 0 and not pc: return (s, 0, 'empty-json')
            return (s, 100 if ms < 800 else 80 if ms < 2000 else 50, f'{ms}ms json c{n} p{pc}')
        if '<rss' in text[:400] or text.startswith('<?xml'):
            n = len(re.findall(r'<ty\b', text))
            if n == 0: return (s, 0, 'empty-xml')
            return (s, 100 if ms < 800 else 80 if ms < 2000 else 50, f'{ms}ms xml ty{n}')
        return (s, 0, f'not-json/xml:{text[:24]}')
    except Exception as e:
        return (s, 0, f'{type(e).__name__}:{str(e)[:32]}')


# ---------- 直播源测活 ----------

def parse_live(text):
    if '#EXTM3U' in text:
        out, group, cur = [], '未分组', None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith('#EXTINF'):
                m = re.search(r'group-title="([^"]*)"', line)
                group = m.group(1) if m else '未分组'
                cur = line.rsplit(',', 1)[-1].strip()
            elif line.startswith('http'):
                out.append((group, cur or '?', line))
        return out
    out, group = [], '未分组'
    for line in text.splitlines():
        line = line.strip()
        if line.endswith(',#genre#'): group = line.split(',')[0]; continue
        if ',' in line:
            name, url = line.split(',', 1)
            if url.strip().startswith('http'): out.append((group, name.strip(), url.strip()))
    return out


def probe_live(item):
    group, name, url = item
    try:
        st, body, _ = get(url, timeout=7, limit=131072)
        if st != 200: return (group, name, url, 0, 0, f'http{st}')
        txt = body.decode('utf-8', 'ignore').lstrip()
        if not txt.startswith('#EXTM3U'):
            return (group, name, url, 0, 0, f'not-m3u8:{txt[:20]}')
        if '#EXT-X-STREAM-INF' in txt:
            cands = []
            for blk in txt.split('#EXT-X-STREAM-INF')[1:]:
                m = re.search(r'BANDWIDTH=(\d+)', blk)
                u = next((clean(l) for l in blk.splitlines() if clean(l)), None)
                if u: cands.append((int(m.group(1)) if m else 0, urljoin(url, u)))
            if not cands: return (group, name, url, 0, 0, 'no-variant')
            cands.sort(); url = cands[0][1]
            st, body, _ = get(url, timeout=7, limit=131072)
            txt = body.decode('utf-8', 'ignore').lstrip()
            if not txt.startswith('#EXTM3U'): return (group, name, url, 0, 0, 'variant-not-m3u8')
        segs = [l.strip() for l in txt.splitlines() if l.strip() and not l.startswith('#')]
        if not segs: return (group, name, url, 0, 0, 'no-segment')
        seg = clean(urljoin(url, segs[0]))
        if not seg: return (group, name, url, 0, 0, 'bad-seg')
        t = time.time()
        st2, data, _ = get(seg, timeout=9, limit=131072, rng='bytes=0-131071')
        ms2 = (time.time() - t) * 1000
        if st2 not in (200, 206): return (group, name, url, 0, 0, f'seg{st2}')
        if len(data) < 1024: return (group, name, url, 20, 0, f'small{len(data)}B')
        kbps = round(len(data) * 8 / max(ms2, 1))
        score = 100 if ms2 < 800 else 80 if ms2 < 2000 else 50 if ms2 < 4000 else 20
        return (group, name, url, score, kbps, f'seg{round(ms2)}ms/{kbps}kbps')
    except Exception as e:
        return (group, name, url, 0, 0, f'{type(e).__name__}')


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sites-only', action='store_true')
    ap.add_argument('--lives-only', action='store_true')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--live-limit', type=int, default=300)
    args = ap.parse_args()
    os.makedirs(DIST, exist_ok=True)

    urls = load_sources()
    print(f'源 {len(urls)} 个')
    fetched = []
    with cf.ThreadPoolExecutor(6) as ex:
        for u, d, err in ex.map(fetch_source, urls):
            if d: fetched.append((u, d)); print(f'  OK   {u[:70]}')
            else: print(f'  FAIL {u[:70]} -> {err}')

    # 汇总 sites / lives
    all_sites, all_lives, meta = [], [], {'spider': None, 'parses': [], 'flags': [], 'doh': [], 'rules': []}
    for u, d in fetched:
        if '_m3u_or_txt' in d:
            all_lives += parse_live(d['_m3u_or_txt']); continue
        for s in d.get('sites') or []:
            try: s['type'] = int(s.get('type', 0))
            except (TypeError, ValueError): s['type'] = -1
            s.setdefault('_src', u); all_sites.append(s)
        for name, val in (('parses', d.get('parses')), ('flags', d.get('flags')),
                          ('doh', d.get('doh')), ('rules', d.get('rules'))):
            if isinstance(val, list): meta[name] += val
        if d.get('spider') and not meta['spider']: meta['spider'] = d['spider']
        for lv in d.get('lives') or []:
            if lv.get('url'): all_lives.append(('lives', lv.get('name', '?'), lv['url']))

    # 去重
    seen, sites = set(), []
    for s in all_sites:
        k = (s.get('api') or '') + '|' + str(s.get('key') or '')
        if k in seen: continue
        seen.add(k); sites.append(s)
    seen2, lives = set(), []
    for it in all_lives:
        if it[2] in seen2: continue
        seen2.add(it[2]); lives.append(it)
    print(f'\n去重后：站点 {len(sites)}（type3={sum(1 for s in sites if s["type"]==3)}）'
          f' 直播 {len(lives)}')

    # 测活
    ok_sites, site_stats = [], []
    if not args.lives_only:
        http_sites = [s for s in sites if s['type'] in (0, 1, 4)]
        print(f'\n测活 type 0/1/4：{len(http_sites)} 个')
        with cf.ThreadPoolExecutor(args.workers) as ex:
            for s, score, detail in ex.map(probe_site, http_sites):
                site_stats.append({'name': s.get('name'), 'api': s.get('api'),
                                   'type': s['type'], 'score': score, 'detail': detail})
                if score > 0:
                    s2 = {k: v for k, v in s.items() if not k.startswith('_')}
                    s2['name'] = f"{s.get('name','')} [{score}]"
                    ok_sites.append(s2)
                    print(f'  [{score:3}] {s.get("name","")[:20]:22} {detail}')
                else:
                    print(f'  [  0] {s.get("name","")[:20]:22} {detail}')

    ok_lives = []
    if not args.sites_only:
        sample = lives[:args.live_limit]
        print(f'\n测活直播：{len(sample)} 个')
        with cf.ThreadPoolExecutor(args.workers) as ex:
            for r in ex.map(probe_live, sample):
                if r[3] > 0:
                    ok_lives.append(r)
                    print(f'  [{r[3]:3}] {r[1][:20]:22} {r[5]}')
        print(f'  可用 {len(ok_lives)}/{len(sample)}')

    # 输出
    vod = {'sites': ok_sites}
    if meta['spider']: vod['spider'] = meta['spider']
    if meta['parses']: vod['parses'] = meta['parses']
    if meta['flags']: vod['flags'] = meta['flags']
    if meta['doh']: vod['doh'] = meta['doh']
    if meta['rules']: vod['rules'] = meta['rules']
    if ok_lives:
        vod['lives'] = [{'name': g, 'type': 0, 'url': '', 'playerType': 1,
                         'epg': '', 'logo': '', 'groups': [{'name': g, 'channels': []}]}
                        for g, _, _ in ok_lives[:1]]
    json.dump(vod, open(os.path.join(DIST, 'fongmi.json'), 'w'), ensure_ascii=False, indent=1)

    m3u = ['#EXTM3U']
    for g, n, u, score, kbps, _ in sorted(ok_lives, key=lambda x: -x[3]):
        m3u.append(f'#EXTINF:-1 group-title="{g}",{n} [{score}]')
        m3u.append(u)
    open(os.path.join(DIST, 'live.m3u'), 'w').write('\n'.join(m3u) + '\n')

    stats = {'built_at': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()),
             'sources': len(urls), 'sources_ok': len(fetched),
             'sites_total': len(sites), 'sites_ok': len(ok_sites),
             'lives_total': len(lives), 'lives_ok': len(ok_lives),
             'parses': meta['parses'], 'flags': meta['flags'], 'doh': meta['doh'],
             'site_detail': site_stats}
    json.dump(stats, open(os.path.join(DIST, 'stats.json'), 'w'), ensure_ascii=False, indent=1)

    # 抽出发给 drpy 测活 worker 的 js 源清单
    def is_js(v):
        v = str(v or '').split('?')[0]
        return v.endswith('.js')

    js_sites = []
    for s in sites:
        api, ext = s.get('api'), s.get('ext')
        if str(api or '').startswith('csp_'):
            continue
        # js 源的判据是 api（引擎）：./lib/drpy2.min.js 或远程 xxx.js。
        # ext 才是规则文件，其扩展名可能是 .js/.txt/.json，不能用来判定。
        if not is_js(api):
            continue
        src = s.get('_src') or ''
        # 从源地址推 raw 根：https://raw.githubusercontent.com/u/r/branch/<path>
        base = ''
        m = re.match(r'(https://raw\.githubusercontent\.com/[^/]+/[^/]+/[^/]+)', src)
        if m:
            base = m.group(1)
        js_sites.append({'name': s.get('name'), 'api': api, 'ext': ext, '_base': base})
    json.dump(js_sites, open(os.path.join(DIST, 'sites_js.json'), 'w'), ensure_ascii=False, indent=1)

    print(f'\n输出：dist/fongmi.json（{len(ok_sites)} 站点） dist/live.m3u（{len(ok_lives)} 频道）')
    print(f'      dist/sites_js.json（{len(js_sites)} 个 js 源，待测活）')


if __name__ == '__main__':
    main()
