#!/usr/bin/env python3
"""探测采集站的搜索接口：确认 FongMi 搜索不走的原因"""
import json, re, urllib.request, urllib.parse, concurrent.futures as cf

UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}
KW = '凡人修仙传'


def get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(400000).decode('utf-8', 'ignore')


def count(body, typ):
    """返回 (条数, 前3个标题)"""
    if typ == 0:
        names = re.findall(r'<name><!\[CDATA\[(.*?)\]\]></name>', body) or \
                re.findall(r'<name>(.*?)</name>', body)
        names = [n for n in names if n.strip()]
        # 第一条通常是站点名，去掉
        return max(0, len(names) - 1), names[1:4]
    try:
        j = json.loads(body)
    except Exception:
        return -1, []
    lst = j.get('list') or []
    return len(lst), [str(v.get('vod_name') or '') for v in lst[:3]]


def probe(site):
    api, typ = str(site['api']), site['type']
    sep = '&' if '?' in api else '?'
    q = urllib.parse.quote(KW)
    forms = []
    if typ == 0:
        forms = [
            ('wd+xml', api + sep + 'ac=videolist&wd=' + q + '&at=xml'),
            ('wd', api + sep + 'ac=videolist&wd=' + q),
        ]
    else:
        forms = [
            ('wd', api + sep + 'ac=videolist&wd=' + q),
            ('detail+wd', api + sep + 'ac=detail&wd=' + q),
        ]
    out = {'name': site['name'], 'api': api, 'type': typ, 'hits': []}
    for label, u in forms:
        try:
            body = get(u)
            n, sample = count(body, typ)
            out['hits'].append({'form': label, 'n': n, 'sample': sample})
            if n and n > 0:
                break
        except Exception as e:
            out['hits'].append({'form': label, 'n': -1, 'err': type(e).__name__})
    return out


if __name__ == '__main__':
    sites = json.load(open('/app/working/fongmi-agg/sites_clean.json'))
    with cf.ThreadPoolExecutor(10) as ex:
        res = list(ex.map(probe, sites))

    ok = [r for r in res if any(h.get('n', 0) > 0 for h in r['hits'])]
    zero = [r for r in res if not any(h.get('n', 0) > 0 for h in r['hits'])]
    print(f'搜索「{KW}」有结果: {len(ok)}/{len(res)}\n')
    for r in sorted(ok, key=lambda x: -max((h.get("n") or 0) for h in x["hits"]))[:15]:
        best = max(r['hits'], key=lambda h: h.get('n') or 0)
        print(f"  {best['n']:>4} 条  [{best['form']}]  {r['name'][:20]}")
        if best.get('sample'):
            print(f"         样例: {' / '.join(str(s)[:18] for s in best['sample'])}")
    print(f'\n无结果: {len(zero)} 个')
    for r in zero[:8]:
        h = r['hits'][0] if r['hits'] else {}
        print(f"  {r['name'][:20]:22} n={h.get('n')} {h.get('err','')}")
    json.dump(res, open('/app/working/fongmi-agg/search_probe.json', 'w'), ensure_ascii=False, indent=1)
