#!/usr/bin/env python3
"""对 clbug 池里的 HTTP 采集站测活：ac=list 校验 + 片库量 + 响应耗时"""
import json, re, time, urllib.request, ssl, concurrent.futures as cf

UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def norm_api(api):
    a = str(api).strip()
    if '?' not in a and not a.endswith('/'):
        a += '/'
    return a


def get(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read(600000).decode('utf-8', 'ignore')


def probe(s):
    api, typ = norm_api(s['api']), s['type']
    sep = '&' if '?' in api else '?'
    r = {'name': s['name'], 'api': api, 'type': typ, 'from': s['from'],
         'ok': False, 'total': 0, 'pages': 0, 'ms': 0, 'err': '', 'kind': ''}
    t0 = time.time()
    try:
        # 优先 JSON
        body = get(api + sep + 'ac=list')
        r['ms'] = int((time.time() - t0) * 1000)
        try:
            j = json.loads(body)
            classes = j.get('class') or []
            r['total'] = int(j.get('total') or 0)
            r['pages'] = int(j.get('pagecount') or 0)
            if classes or r['pages'] > 0:
                r['ok'] = True
                r['kind'] = 'json'
                return r
        except Exception:
            pass
        # 退回 XML
        if typ == 0:
            body = get(api + sep + 'ac=list&at=xml')
            r['ms'] = int((time.time() - t0) * 1000)
            if '<rss' in body or '<list' in body:
                tys = re.findall(r'<ty id="(\d+)">', body)
                pg = re.search(r'pagecount="(\d+)"', body) or re.search(r'<pagecount>(\d+)', body)
                r['pages'] = int(pg.group(1)) if pg else 0
                if tys:
                    r['ok'] = True
                    r['kind'] = 'xml'
                    return r
        r['err'] = 'no-class'
    except Exception as e:
        r['ms'] = int((time.time() - t0) * 1000)
        r['err'] = type(e).__name__
    return r


if __name__ == '__main__':
    raw = json.load(open('/app/working/fongmi-agg/clbug_http_sites.json'))
    # 按完整 api 去重
    seen, uniq = {}, []
    for s in raw:
        k = norm_api(s['api']).rstrip('/').lower()
        if k not in seen:
            seen[k] = s
            uniq.append(s)
    print(f'待测 {len(uniq)} 个（原 {len(raw)}，按 api 去重后）\n')

    with cf.ThreadPoolExecutor(12) as ex:
        res = list(ex.map(probe, uniq))

    ok = [r for r in res if r['ok']]
    print(f'测活通过: {len(ok)}/{len(res)}\n')
    print('--- 通过的站（按片库量）---')
    for r in sorted(ok, key=lambda x: -x['total'])[:45]:
        print(f"  {r['total']:>8} 部  {r['pages']:>5}页  {r['ms']:>5}ms  {r['kind']:<4} {r['name'][:20]:22} {r['api'][:52]}")

    print('\n--- 失败的站 ---')
    fails = [r for r in res if not r['ok']]
    from collections import Counter
    print('失败原因分布:', dict(Counter(r['err'] for r in fails)))
    for r in fails[:20]:
        print(f"  {r['name'][:20]:22} {r['err']:<15} {r['api'][:55]}")

    json.dump(res, open('/app/working/fongmi-agg/clbug_probe.json', 'w'), ensure_ascii=False, indent=1)
