#!/usr/bin/env python3
"""对指定频道的所有线路做真实可达性测试，输出可用线路排序"""
import json, re, ssl, sys, time, urllib.request, concurrent.futures as cf
from urllib.parse import urljoin

UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE


def fetch(url, timeout=8, limit=120_000):
    req = urllib.request.Request(url, headers=UA)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        data = r.read(limit)
    return data, int((time.time() - t0) * 1000)


def check(url):
    """返回 (ok, ms, 说明)：能拿到 m3u8 且含分片地址才算通"""
    try:
        data, ms = fetch(url)
        txt = data.decode('utf-8', 'ignore')
        if '#EXTM3U' not in txt:
            # 可能直接是 ts
            return (len(data) > 5000), ms, 'ts?%d' % len(data)
        lines = [l.strip() for l in txt.splitlines() if l.strip() and not l.startswith('#')]
        if not lines:
            return False, ms, 'empty-playlist'
        # 主列表 → 子列表
        sub = urljoin(url, lines[0])
        if sub != url and '.ts' not in sub:
            try:
                d2, ms2 = fetch(sub)
                t2 = d2.decode('utf-8', 'ignore')
                if '#EXTM3U' in t2:
                    segs = [l.strip() for l in t2.splitlines() if l.strip() and not l.startswith('#')]
                    if segs:
                        sg = urljoin(sub, segs[0])
                        d3, ms3 = fetch(sg, timeout=8, limit=80_000)
                        if len(d3) > 1000:
                            return True, ms + ms2 + ms3, 'seg%dk' % (len(d3) // 1024)
                return False, ms2, 'sub-no-seg'
            except Exception:
                return False, ms, 'sub-fail'
        return True, ms, 'direct'
    except Exception as e:
        return False, 0, type(e).__name__


def test_channel(item):
    name, routes = item
    with cf.ThreadPoolExecutor(24) as ex:
        res = list(ex.map(lambda r: (r, check(r['url'])), routes))
    good = [(r, ms, note) for r, (ok, ms, note) in res if ok]
    good.sort(key=lambda x: x[1])
    return name, len(routes), good


if __name__ == '__main__':
    merged = json.load(open('/app/working/fongmi-agg/live_merged.json'))
    targets = sys.argv[1:] or ['cctv-1综合', 'cctv13新闻', '湖南卫视', '浙江卫视', '东方卫视', '江苏卫视']
    keys = []
    for t in targets:
        k = re.sub(r'\s+', '', t).lower()
        if k in merged:
            keys.append(k)
        else:
            for kk in merged:
                if k in kk or kk in k:
                    keys.append(kk); break
    print(f'测试 {len(keys)} 个频道\n')
    out = {}
    for k in keys:
        name, n, good = test_channel((k, merged[k]))
        out[k] = {'name': merged[k][0]['name'], 'routes': [g[0]['url'] for g in good],
                  'notes': [(g[0]['src'], g[1], g[2]) for g in good]}
        print(f"{merged[k][0]['name'][:20]:24} 共 {n:>3} 线 → 通 {len(good):>2}")
        for r, ms, note in good[:5]:
            print(f'    {ms:>5}ms {note:<10} [{r["src"][:14]}] {r["url"][:66]}')
        print()
    json.dump(out, open('/app/working/fongmi-agg/live_tested_core.json', 'w'), ensure_ascii=False, indent=1)
