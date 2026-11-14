#!/usr/bin/env python3
"""probe_api.py —— 批量测活 TVBox 采集站（type 0/1）

判据（不是只看 200）：
  type 1 → ?ac=videolist&pg=1 返回 JSON 且 list 非空
  type 0 → ?ac=videolist&at=xml&pg=1 返回 XML 且 <video> 非空
输出 ok_api.json（可用站点 + 片库量 + 耗时）
"""
import concurrent.futures as cf, json, re, sys, time
import urllib.request, urllib.error

UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36'}


def fetch(url, timeout=12, limit=400000):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(limit)


def probe(site):
    api = str(site.get('api') or '')
    typ = site.get('type')
    if not api.startswith('http'):
        return {**site, '_ok': False, '_err': 'non-http'}
    sep = '&' if '?' in api else '?'
    t0 = time.time()
    try:
        if typ == 0:
            url = api + sep + 'ac=videolist&at=xml&pg=1'
            st, body = fetch(url)
            txt = body.decode('utf-8', 'ignore')
            n = len(re.findall(r'<video>', txt))
            if n == 0:
                return {**site, '_ok': False, '_err': f'xml-empty({len(body)}B)'}
            m = re.search(r'recordcount="(\d+)"', txt)
            total = int(m.group(1)) if m else 0
            return {**site, '_ok': True, '_total': total, '_ms': round((time.time()-t0)*1000)}
        else:
            url = api + sep + 'ac=videolist&pg=1'
            st, body = fetch(url)
            j = json.loads(body.decode('utf-8', 'ignore'))
            lst = j.get('list') or []
            if not lst:
                return {**site, '_ok': False, '_err': 'json-list-empty'}
            return {**site, '_ok': True, '_total': int(j.get('total') or 0),
                    '_ms': round((time.time()-t0)*1000)}
    except urllib.error.HTTPError as e:
        return {**site, '_ok': False, '_err': f'http{e.code}'}
    except Exception as e:
        return {**site, '_ok': False, '_err': type(e).__name__}


def main():
    data = json.load(open(sys.argv[1]))
    sites = (data.get('sites') if isinstance(data, dict) else data) or []
    sites = [s for s in sites if s.get('type') in (0, 1)]
    print(f'待测 {len(sites)} 个采集站', flush=True)

    ok, fail = [], 0
    with cf.ThreadPoolExecutor(16) as ex:
        for i, r in enumerate(ex.map(probe, sites), 1):
            if r['_ok']:
                ok.append(r)
            else:
                fail += 1
            if i % 20 == 0:
                print(f'  {i}/{len(sites)} 通过 {len(ok)}', flush=True)

    ok.sort(key=lambda x: -x.get('_total', 0))
    print(f'\n可用 {len(ok)}/{len(sites)}（{fail} 失败）')
    for r in ok[:25]:
        print(f"  {r['_total']:>8} 部  {r['_ms']:>5}ms  {str(r['name'])[:20]:22} {r['api'][:50]}")

    total = sum(r.get('_total', 0) for r in ok)
    print(f'\n合计片库 ≈ {total:,} 部')
    json.dump(ok, open('state/ok_api.json', 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
