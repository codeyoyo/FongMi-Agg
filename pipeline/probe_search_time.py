#!/usr/bin/env python3
"""测每个采集站的搜索耗时，用于给 clean 版排序（快的在前）"""
import json, re, time, urllib.request, urllib.parse, concurrent.futures as cf

UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}
KW = '凡人修仙传'


def timed_get(url, timeout=10):
    req = urllib.request.Request(url, headers=UA)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(400000).decode('utf-8', 'ignore')
        return body, (time.time() - t0) * 1000, None
    except Exception as e:
        return None, (time.time() - t0) * 1000, type(e).__name__


def count(body, typ):
    if body is None:
        return 0
    if typ == 0:
        names = re.findall(r'<name><!\[CDATA\[(.*?)\]\]></name>', body) or \
                re.findall(r'<name>(.*?)</name>', body)
        return max(0, len([n for n in names if n.strip()]) - 1)
    try:
        return len(json.loads(body).get('list') or [])
    except Exception:
        return 0


def probe(site):
    api, typ = str(site['api']), site['type']
    sep = '&' if '?' in api else '?'
    q = urllib.parse.quote(KW)
    url = api + sep + ('ac=videolist&wd=' + q + '&at=xml' if typ == 0 else 'ac=videolist&wd=' + q)
    body, ms, err = timed_get(url)
    n = count(body, typ)
    return {'name': site['name'], 'api': api, 'type': typ,
            'n': n, 'ms': int(ms), 'err': err}


if __name__ == '__main__':
    sites = json.load(open('/app/working/fongmi-agg/state/sites_verified_pool.json'))
    with cf.ThreadPoolExecutor(12) as ex:
        res = list(ex.map(probe, sites))

    good = [r for r in res if r['n'] > 0]
    bad = [r for r in res if r['n'] == 0]
    good.sort(key=lambda x: x['ms'])
    print(f'搜得到 {len(good)} / 搜不到 {len(bad)}  共 {len(res)}\n')
    print('按耗时排序:')
    for r in good:
        print(f"  {r['ms']:>5}ms  {r['n']:>3} 条  {r['name'][:22]}")
    print('\n搜不到:')
    for r in bad:
        print(f"  {r['ms']:>5}ms  {r['name'][:22]}  {r['err'] or 'empty'}")
    json.dump(res, open('/app/working/fongmi-agg/state/search_timing.json', 'w'), ensure_ascii=False, indent=1)
