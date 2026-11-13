#!/usr/bin/env python3
"""拉取 tvbox.clbug.com 的 115 个订阅源，解析出其中的站点与直播源"""
import json, re, urllib.request, ssl, concurrent.futures as cf

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        raw = r.read(4_000_000)
        enc = 'utf-8'
        ct = r.headers.get('Content-Type', '') or ''
        m = re.search(r'charset=([\w-]+)', ct, re.I)
        if m:
            enc = m.group(1)
        return raw.decode(enc, 'ignore'), r.status


def parse_cfg(text):
    """尽量从响应里抽出 VodConfig（可能是 JSON，也可能带 BOM/前后杂质）"""
    t = text.lstrip('\ufeff').strip()
    try:
        d = json.loads(t)
        return d if isinstance(d, dict) else None
    except Exception:
        pass
    # 从第一个 { 到最后一个 }
    i, j = t.find('{'), t.rfind('}')
    if i >= 0 and j > i:
        for seg in (t[i:j + 1],):
            try:
                return json.loads(seg)
            except Exception:
                pass
    return None


def probe(item):
    idx, name, url = item['idx'], item['name'], item['url']
    r = {'idx': idx, 'name': name, 'url': url, 'ok': False,
         'sites': 0, 'lives': 0, 'http': 0, 'err': ''}
    try:
        text, code = fetch(url)
        r['http'] = code
        cfg = parse_cfg(text)
        if not cfg:
            r['err'] = 'not-json(%dB)' % len(text)
            return r
        sites = cfg.get('sites') or []
        lives = cfg.get('lives') or []
        r['ok'] = True
        r['sites'] = len(sites) if isinstance(sites, list) else 0
        r['lives'] = len(lives) if isinstance(lives, list) else 0
        r['cfg'] = cfg
    except Exception as e:
        r['err'] = type(e).__name__
    return r


if __name__ == '__main__':
    rows = json.load(open('/tmp/rows.json'))
    items = []
    for i, o in enumerate(rows):
        c = o['cells']
        if len(c) >= 3 and c[2].startswith('http'):
            items.append({'idx': int(c[0]) if c[0].isdigit() else i, 'name': c[1], 'url': c[2]})

    print(f'待探测 {len(items)} 个源\n')
    with cf.ThreadPoolExecutor(12) as ex:
        res = list(ex.map(probe, items))

    ok = [r for r in res if r['ok']]
    print(f'配置可解析: {len(ok)}/{len(res)}')
    total_sites = sum(r['sites'] for r in ok)
    total_lives = sum(r['lives'] for r in ok)
    print(f'合计 sites={total_sites}  lives={total_lives}\n')
    print('--- 可用源 ---')
    for r in sorted(ok, key=lambda x: -x['sites'])[:40]:
        print(f"  {r['idx']:>3} {r['name'][:14]:16} sites={r['sites']:>4} lives={r['lives']:>4}  {r['url'][:58]}")
    print('\n--- 失败源 ---')
    for r in [x for x in res if not x['ok']][:40]:
        print(f"  {r['idx']:>3} {r['name'][:14]:16} http={r['http']} {r['err']:<18} {r['url'][:52]}")
    json.dump([{k: v for k, v in r.items() if k != 'cfg'} for r in res],
              open('/app/working/fongmi-agg/clbug_sources.json', 'w'), ensure_ascii=False, indent=1)
    json.dump([{'name': r['name'], 'url': r['url'], 'cfg': r['cfg']} for r in ok],
              open('/app/working/fongmi-agg/clbug_cfgs.json', 'w'), ensure_ascii=False)
