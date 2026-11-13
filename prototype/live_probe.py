"""直播源测活：txt(频道名,url + #genre#) / m3u -> 并发探测 -> 评分 -> 输出 m3u
判据：能取到主播放列表 -> 能取到子流/分片 -> 计时与吞吐
"""
import re, time, ssl, json, sys, urllib.request, concurrent.futures as cf
from urllib.parse import urljoin

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36'}

def parse_txt(text):
    out, group = [], '未分组'
    for line in text.splitlines():
        line = line.strip()
        if not line: continue
        if line.endswith(',#genre#'):
            group = line.split(',')[0]; continue
        if ',' in line:
            name, url = line.split(',', 1)
            if url.startswith('http'): out.append((group, name.strip(), url.strip()))
    return out

def parse_m3u(text):
    out, group = [], '未分组'
    cur = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#EXTINF'):
            m = re.search(r'group-title="([^"]*)"', line)
            group = m.group(1) if m else '未分组'
            cur = line.rsplit(',', 1)[-1].strip()
        elif line.startswith('http'):
            out.append((group, cur or '?', line))
    return out

def _clean(u):
    """去掉控制字符并校验是可用 URL；m3u8 属性续行常被误当 URL"""
    u = ''.join(ch for ch in (u or '') if ch.isprintable()).strip()
    if not u or u.startswith('#') or ' ' in u:
        return None
    if '=' in u and '/' not in u:   # 形如 RESOLUTION=1920x1080 的属性行
        return None
    return u

def _get(url, rng=None, timeout=6, limit=131072):
    url = _clean(url)
    if url is None:
        raise ValueError('bad-url')
    req = urllib.request.Request(url, headers=UA)
    if rng: req.add_header('Range', rng)
    t = time.time()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        data = r.read(limit)
        return r.status, data, (time.time() - t) * 1000

def probe(item):
    group, name, url = item
    try:
        st, body, ms = _get(url)
        if st != 200: return (group, name, url, 0, 0, f'http{st}')
        txt = body.decode('utf-8', 'ignore').lstrip()
        # 关键：200 也可能是假的——geo-block 常返回纯文本
        if not txt.startswith('#EXTM3U'):
            return (group, name, url, 0, 0, f'not-m3u8:{txt[:24]}')
        # 主播放列表 -> 取最低码率子流
        if '#EXT-X-STREAM-INF' in txt:
            cands = []
            for blk in txt.split('#EXT-X-STREAM-INF')[1:]:
                m = re.search(r'BANDWIDTH=(\d+)', blk)
                u = next((_clean(l) for l in blk.splitlines() if _clean(l)), None)
                if u: cands.append((int(m.group(1)) if m else 0, urljoin(url, u)))
            if not cands: return (group, name, url, 0, 0, 'no-variant')
            cands.sort()
            url = cands[0][1]
            st, body, ms = _get(url)
            txt = body.decode('utf-8', 'ignore').lstrip()
            if not txt.startswith('#EXTM3U'):
                return (group, name, url, 0, 0, 'variant-not-m3u8')
        # 取首个分片
        segs = [l.strip() for l in txt.splitlines() if l.strip() and not l.startswith('#')]
        if not segs: return (group, name, url, 0, 0, 'no-segment')
        seg = _clean(urljoin(url, segs[0]))
        st2, data2, ms2 = _get(seg, 'bytes=0-131071', timeout=8)
        if st2 not in (200, 206): return (group, name, url, 0, 0, f'seg{st2}')
        kbps = round(len(data2) * 8 / max(ms2, 1))  # bit/ms = kbit/s
        score = 100 if ms2 < 800 else 80 if ms2 < 2000 else 50 if ms2 < 4000 else 20
        if len(data2) < 1024: score = min(score, 20)
        return (group, name, url, score, kbps, f'{round(ms)}ms/seg{round(ms2)}ms/{kbps}kbps')
    except Exception as e:
        return (group, name, url, 0, 0, f'{type(e).__name__}:{str(e)[:28]}')

def main():
    src = sys.argv[1]
    raw = urllib.request.urlopen(urllib.request.Request(src, headers=UA), timeout=15, context=ctx).read().decode('utf-8', 'ignore')
    items = parse_m3u(raw) if ('#EXTM3U' in raw or src.endswith('.m3u')) else parse_txt(raw)
    print(f"源: {src}\n频道条目: {len(items)}（去重前）")
    seen, uniq = set(), []
    for it in items:
        if it[2] not in seen: seen.add(it[2]); uniq.append(it)
    print(f"去重后: {len(uniq)}\n")

    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    sample = uniq[:limit]
    results = []
    with cf.ThreadPoolExecutor(8) as ex:
        for r in ex.map(probe, sample):
            results.append(r)
            print(f"  [{r[3]:>3}] {r[1][:20]:22} {r[0][:10]:12} {r[5]}")

    ok = [r for r in results if r[3] > 0]
    print(f"\n可用 {len(ok)}/{len(sample)}")
    out = ['#EXTM3U']
    for group, name, url, score, kbps, _ in sorted(ok, key=lambda x: -x[3]):
        out.append(f'#EXTINF:-1 group-title="{group}",{name} [{score}]')
        out.append(url)
    p = '/app/working/fongmi-agg/prototype/sample-live.m3u'
    open(p, 'w').write('\n'.join(out) + '\n')
    print(f"已输出 {p}（{len(ok)} 条）")

if __name__ == '__main__':
    main()
