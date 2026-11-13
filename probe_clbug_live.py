#!/usr/bin/env python3
"""测 clbug 池的 84 个直播源：能否拉到列表 + 频道数 + 抽样探测分片可播性"""
import json, re, ssl, time, urllib.request, concurrent.futures as cf
from urllib.parse import urlparse

UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def fetch(url, timeout=20, limit=3_000_000):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read(limit).decode('utf-8', 'ignore'), r.status


def count_channels(text):
    """m3u 或 txt 格式的频道数"""
    if '#EXTINF' in text:
        return len(re.findall(r'#EXTINF', text)), 'm3u'
    if '#genre#' in text:
        n = 0
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' in line.split(',')[0]:
                continue
            if ',' in line and ('http' in line):
                n += 1
        return n, 'txt'
    # JSON 格式（groups 数组）
    try:
        d = json.loads(text)
        if isinstance(d, list):
            return sum(len(g.get('channel') or []) for g in d if isinstance(g, dict)), 'json'
    except Exception:
        pass
    return 0, 'unknown'


def probe(item):
    r = dict(item, ok=False, ch=0, kind='', ms=0, err='', size=0)
    t0 = time.time()
    try:
        text, code = fetch(item['url'])
        r['ms'] = int((time.time() - t0) * 1000)
        r['size'] = len(text)
        n, kind = count_channels(text)
        r['ch'], r['kind'] = n, kind
        if n > 0:
            r['ok'] = True
        else:
            r['err'] = 'no-channels(%dB)' % len(text)
    except Exception as e:
        r['ms'] = int((time.time() - t0) * 1000)
        r['err'] = type(e).__name__
    return r


if __name__ == '__main__':
    lives = json.load(open('/app/working/fongmi-agg/clbug_lives.json'))
    print(f'待测 {len(lives)} 个直播源\n')
    with cf.ThreadPoolExecutor(12) as ex:
        res = list(ex.map(probe, lives))
    ok = [r for r in res if r['ok']]
    print(f'可拉取到频道列表: {len(ok)}/{len(res)}')
    print(f'合计频道数: {sum(r["ch"] for r in ok)}\n')
    for r in sorted(ok, key=lambda x: -x['ch'])[:35]:
        print(f"  {r['ch']:>5} 频道  {r['kind']:<4} {r['ms']:>5}ms  {r['name'][:18]:20} {r['url'][:52]}")
    print('\n--- 失败 ---')
    for r in [x for x in res if not x['ok']][:20]:
        print(f"  {r['name'][:18]:20} {r['err']:<20} {r['url'][:52]}")
    json.dump(res, open('/app/working/fongmi-agg/clbug_live_probe.json', 'w'), ensure_ascii=False, indent=1)
