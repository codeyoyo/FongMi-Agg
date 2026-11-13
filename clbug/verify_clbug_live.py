#!/usr/bin/env python3
"""对候选直播源抽样测分片：判断"列表可拉"之外，频道是否真能播"""
import json, re, ssl, time, urllib.request, concurrent.futures as cf
from urllib.parse import urljoin

UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

CANDIDATES = [
    'https://gh-proxy.com/https://raw.githubusercontent.com/',
    'https://epg.pw/test_channels.m3u',
    'https://sub.ottiptv.cc/huyayqk.m3u',
    'https://sub.ottiptv.cc/douyuyqk.m3u',
    'https://sub.ottiptv.cc/yylunbo.m3u',
    'https://sub.ottiptv.cc/bililive.m3u',
    'https://zb.7778.uk/starlink.m3u',
    'https://cdn.jsdelivr.net/gh/Guovin/iptv-api@gd/output/result.m3u',
]


def fetch(url, timeout=15, limit=400_000):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read(limit), r.headers.get('Content-Type', '')


def extract_urls(text):
    out = []
    if '#EXTINF' in text:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '://' in line:
                out.append(line)
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '#genre#' in line:
                continue
            parts = line.split(',')
            if len(parts) < 2:
                continue
            for u in parts[1].split('#'):
                u = u.split('$')[0].strip()
                if '://' in u:
                    out.append(u)
    return out


def check_stream(u, timeout=10):
    """m3u8 取主列表→子列表→首个分片；或直接取分片"""
    try:
        t0 = time.time()
        data, ct = fetch(u, timeout=timeout, limit=200_000)
        ms = int((time.time() - t0) * 1000)
        txt = data.decode('utf-8', 'ignore')
        if '#EXTM3U' in txt:
            # 可能是子列表，取第一个非注释行
            subs = [l.strip() for l in txt.splitlines() if l.strip() and not l.startswith('#')]
            if subs:
                su = urljoin(u, subs[0])
                if su != u and not su.endswith('.ts'):
                    d2, _ = fetch(su, timeout=timeout, limit=200_000)
                    txt = d2.decode('utf-8', 'ignore')
                    if '#EXTM3U' in txt:
                        segs = [l.strip() for l in txt.splitlines() if l.strip() and not l.startswith('#')]
                        if segs:
                            sg = urljoin(su, segs[0])
                            d3, _ = fetch(sg, timeout=timeout, limit=150_000)
                            return True, ms, len(d3)
                    return True, ms, len(d2)
            return True, ms, len(data)
        if len(data) > 2000:  # 直接是 ts 流
            return True, ms, len(data)
        return False, ms, 0
    except Exception as e:
        return False, 0, 0


def test_source(url):
    r = {'url': url, 'ch': 0, 'tested': 0, 'live': 0, 'rate': 0.0, 'samples': []}
    try:
        data, _ = fetch(url, timeout=20, limit=3_000_000)
        text = data.decode('utf-8', 'ignore')
        urls = extract_urls(text)
        r['ch'] = len(urls)
        # 均匀抽样 8 个
        if urls:
            step = max(1, len(urls) // 8)
            picks = urls[::step][:8]
            r['tested'] = len(picks)
            with cf.ThreadPoolExecutor(8) as ex:
                res = list(ex.map(lambda u: (u, check_stream(u)), picks))
            live = [u for u, (ok, ms, sz) in res if ok]
            r['live'] = len(live)
            r['rate'] = round(len(live) / max(1, len(picks)), 2)
            r['samples'] = [(u[:70], ok, ms, sz) for u, (ok, ms, sz) in res[:3]]
    except Exception as e:
        r['err'] = type(e).__name__
    return r


if __name__ == '__main__':
    probe = json.load(open('/app/working/fongmi-agg/clbug_live_probe.json'))
    ok = [p for p in probe if p['ok'] and p['ch'] >= 400 and not p['url'].startswith('http://127.')]
    ok.sort(key=lambda x: -x['ch'])
    print(f'候选源（频道≥400 且非本地）: {len(ok)}\n')
    keep = []
    for item in ok[:24]:
        r = test_source(item['url'])
        tag = '✅' if r['rate'] >= 0.5 else ('⚠️' if r['rate'] > 0 else '❌')
        print(f"{tag} {r['ch']:>5}频道 存活 {r['live']}/{r['tested']}  {item['name'][:18]:20} {item['url'][:50]}")
        if r['rate'] >= 0.4:
            keep.append({'name': item['name'], 'url': item['url'], 'ch': r['ch'], 'rate': r['rate']})
    print(f'\n通过抽样（≥40% 可播）: {len(keep)}')
    for k in keep:
        print(f"  {k['ch']:>5}频道 {k['rate']:.0%}  {k['name'][:20]:22} {k['url'][:56]}")
    json.dump(keep, open('/app/working/fongmi-agg/clbug_live_kept.json', 'w'), ensure_ascii=False, indent=1)
