#!/usr/bin/env python3
"""verify_clean.py —— 深度验证干净站的可用性

对每个站检查三层：
  L1  ac=list         分类列表非空？
  L2  ac=videolist    视频列表非空？
  L3  ac=detail       首页第一条的详情能拿到？（真正可播的前提）

只打印层级结果与耗时，不输出影片标题。
"""
import concurrent.futures as cf, json, re, sys, urllib.request, time

UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}


def get(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(200000).decode('utf-8', 'ignore'), (time.time() - t0) * 1000


def parse_list(body, typ):
    """返回 [(id, name)]"""
    if typ == 0:
        pairs = re.findall(r'<id>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</id>\s*<name>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</name>', body)
        return [(a, b) for a, b in pairs]
    try:
        j = json.loads(body)
    except Exception:
        return []
    return [(str(v.get('vod_id') or ''), str(v.get('vod_name') or '')) for v in (j.get('list') or [])]


def verify(site):
    api, typ = str(site.get('api') or ''), site.get('type')
    sep = '&' if '?' in api else '?'
    out = {'name': site['name'], '_total': site.get('_total', 0), 'L1': 0, 'L2': 0, 'L3': 0, 'ms': 0}
    try:
        # L1 分类
        _, b, ms = get(api + sep + 'ac=list')
        classes = re.findall(r'<ty id="(\d+)"', b) if typ == 0 else \
            [str(c.get('type_id')) for c in (json.loads(b).get('class') or [])] if b.strip().startswith('{') else []
        out['L1'] = len(classes)
        out['ms'] = int(ms)
        if not classes:
            return out
        # L2 视频列表：各家对 t= 的用法不一致，依次试三种形态
        tid = classes[0]
        cands = [
            (api + sep + f'ac=videolist&t={tid}&pg=1&at=xml') if typ == 0 else (api + sep + f'ac=videolist&t={tid}&pg=1'),
            (api + sep + 'ac=videolist&pg=1&at=xml') if typ == 0 else (api + sep + 'ac=videolist&pg=1'),
            (api + sep + 'ac=detail&pg=1&at=xml') if typ == 0 else (api + sep + 'ac=detail&pg=1'),
        ]
        lst = []
        for u in cands:
            try:
                _, b2, _ = get(u)
                lst = parse_list(b2, typ)
                if lst:
                    out['_via'] = cands.index(u)
                    break
            except Exception:
                continue
        out['L2'] = len(lst)
        if not lst:
            return out
        # L3 详情
        vid = lst[0][0]
        if not vid:
            return out
        url3 = (api + sep + f'ac=videolist&ids={vid}&at=xml') if typ == 0 else \
               (api + sep + f'ac=videolist&ids={vid}')
        _, b3, _ = get(url3)
        detail = parse_list(b3, typ) or parse_list(b3, 1 - typ)
        out['L3'] = 1 if detail else 0
    except Exception as e:
        out['err'] = type(e).__name__
    return out


def main():
    sites = json.load(open(sys.argv[1]))
    with cf.ThreadPoolExecutor(12) as ex:
        res = list(ex.map(verify, sites))
    res.sort(key=lambda x: (-(x['L1'] and x['L2'] and x['L3']), -x['_total']))

    full = [r for r in res if r['L1'] and r['L2'] and r['L3']]
    half = [r for r in res if (r['L1'] or r['L2']) and not (r['L1'] and r['L2'] and r['L3'])]
    dead = [r for r in res if not r['L1'] and not r['L2']]

    print(f'三层全通 {len(full)} / 部分可用 {len(half)} / 不可用 {len(dead)}  共 {len(res)}\n')
    print('三层全通（分类 / 列表 / 详情 都拿得到）:')
    for r in full[:20]:
        print(f"  {r['_total']:>8} 部  {r['ms']:>4}ms  L1={r['L1']:>2} L2={r['L2']:>2}  {r['name'][:22]}")
    if half:
        print('\n部分可用:')
        for r in half[:10]:
            print(f"  {r['_total']:>8} 部  L1={r['L1']:>2} L2={r['L2']:>2} L3={r['L3']}  {r['name'][:22]}  {r.get('err','')}")
    if dead:
        print('\n不可用:')
        for r in dead[:10]:
            print(f"  {r['_total']:>8} 部  L1={r['L1']} L2={r['L2']}  {r['name'][:22]}  {r.get('err','')}")

    json.dump(res, open('verify_result.json', 'w'), ensure_ascii=False, indent=1)
    print(f"\n三层全通合计片库 ≈ {sum(r['_total'] for r in full):,} 部")


if __name__ == '__main__':
    main()
