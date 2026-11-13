#!/usr/bin/env python3
"""build_agg.py —— 为服务端聚合 API 预生成"源 → 分类(tid)"映射

输出 dist2/agg_srcs.json：
{
  "other": {"buckets": [{"name":"电影","srcs":[{"api":..,"type":..,"tid":"1","total":171784,"name":"暴风"}, ...]}, ...]},
  "adult": {...}
}

标准分类桶把各源五花八门的 tid 对齐，App 里只看到 6 个分类，
每个分类背后是 N 个源合并。
"""
import json, os, re, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE, 'dist2')
UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}

# 分类桶 → 归类关键词（按顺序匹配，先命中先用）
BUCKETS = [
    ('电影', ['电影', '片']),
    ('电视剧', ['电视剧', '连续剧', '剧集', '剧']),
    ('综艺', ['综艺']),
    ('动漫', ['动漫', '动画']),
    ('纪录片', ['纪录']),
]
MAX_SRC_PER_BUCKET = 12   # Cloudflare 每请求 subrequest 上限 50，留足余量


def fetch_classes(site):
    api, typ = str(site.get('api') or ''), site.get('type')
    sep = '&' if '?' in api else '?'
    url = api + sep + ('ac=list&at=xml' if typ == 0 else 'ac=list')
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=12) as r:
            body = r.read(300000).decode('utf-8', 'ignore')
    except Exception as e:
        return {**site, '_cls': [], '_cerr': type(e).__name__}

    pairs = []
    if typ == 0:
        seg = re.search(r'<class>(.*?)</class>', body, re.S)
        text = seg.group(1) if seg else body
        for m in re.finditer(r'<ty\s+id="([^"]+)"\s*>([^<]*)</ty>', text):
            pairs.append((m.group(1).strip(), m.group(2).strip()))
    else:
        try:
            j = json.loads(body)
            for c in (j.get('class') or []):
                pairs.append((str(c.get('type_id')), str(c.get('type_name') or '')))
        except Exception as e:
            return {**site, '_cls': [], '_cerr': 'json:' + type(e).__name__}
    return {**site, '_cls': pairs[:80]}


def bucket_of(name):
    for b, kws in BUCKETS:
        for k in kws:
            if k in name:
                return b
    return '其它'


def main():
    kinds = json.load(open(os.path.join(BASE, 'kinds2.json')))
    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(fetch_classes, kinds))

    # 播放实测结果（play_probe.py）：只把"详情能出 + 播放地址真的是 m3u8"的源收进池子
    quality = {}
    try:
        for r in json.load(open(os.path.join(BASE, 'play_probe.json'))):
            quality[r['name']] = {'play': int(r.get('play_ok') or 0),
                                  'n': int(r.get('n') or 0),
                                  'rate': float(r.get('rate') or 0)}
        print(f'播放实测：{sum(1 for v in quality.values() if v["play"] > 0)}/{len(quality)} 源有可播样本')
    except FileNotFoundError:
        print('!! 没有 play_probe.json，本轮不做播放筛选')

    out = {}
    for grp, want in (('other', 'clean'), ('adult', 'adult')):
        srcs = [r for r in rows if r['_kind'] == want and r.get('_cls')]
        if quality:
            for r in srcs:
                r['_q'] = quality.get(r['name'], {})
            good = [r for r in srcs if r['_q'].get('play', 0) >= 2]
            if len(good) < 4:                      # 太少了就放宽到"至少 1 个能播"
                good = [r for r in srcs if r['_q'].get('play', 0) >= 1]
            if len(good) >= 3:
                srcs = good
        srcs.sort(key=lambda x: (-x.get('_q', {}).get('rate', 0), -int(x.get('_total') or 0)))
        buckets, used = {}, {}
        for r in srcs:
            # 每个源在每个桶最多贡献 1 个 tid
            seen = set()
            for tid, cname in r['_cls']:
                b = bucket_of(cname)
                if b in seen:
                    continue
                seen.add(b)
                if used.get(b, 0) >= MAX_SRC_PER_BUCKET:
                    continue
                used[b] = used.get(b, 0) + 1
                buckets.setdefault(b, []).append({
                    'name': r['name'], 'api': r['api'], 'type': r['type'],
                    'tid': tid, 'cname': cname, 'total': int(r.get('_total') or 0),
                })
        order = ['电影', '电视剧', '综艺', '动漫', '纪录片', '其它']
        bl = [{'name': b, 'srcs': buckets[b]} for b in order if buckets.get(b)]
        out[grp] = {'buckets': bl}
        print(f'{grp}: {len(srcs)} 源 → ' +
              ', '.join(f"{b['name']}{len(b['srcs'])}" for b in bl))

    json.dump(out, open(os.path.join(DIST, 'agg_srcs.json'), 'w'), ensure_ascii=False)
    print('→ dist2/agg_srcs.json', os.path.getsize(os.path.join(DIST, 'agg_srcs.json')), 'B')


if __name__ == '__main__':
    main()
