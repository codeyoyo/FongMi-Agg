#!/usr/bin/env python3
"""classify_sites.py —— 判定采集站性质（正经影视 / 成人）

判据两层：
  1. 站名关键词（快，但会漏）
  2. 内容抽样：拉首 20 条标题，统计成人关键词命中率（准）

只输出命中率与判定，不输出标题原文。
"""
import json, re, sys, urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}

# 内容侧关键词（用于统计标题命中率）
CONTENT_WORDS = [
    '无码', '有码', '番号', '自慰', '口交', '肛', '淫', '骚', '裸', '里番',
    '工口', '成人', '情色', '三级', '肉棒', '射精', '潮吹', '中出', '内射',
    'jav', 'porn', 'xxx', 'hentai', 'adult', 'av女', '麻豆', '天美', '果冻',
    'swag', 'onlyfans', 'fc2', '萝莉', '痴女', '调教',
]
# 站名侧关键词
NAME_WORDS = ['番号', '杏吧', '奶子', '搜av', '大奶', '情色', '色', 'av资源', '麻豆', '天美']


def fetch_titles(api, typ):
    sep = '&' if '?' in api else '?'
    url = api + sep + ('ac=videolist&at=xml&pg=1' if typ == 0 else 'ac=videolist&pg=1')
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read(300000).decode('utf-8', 'ignore')
    if typ == 0:
        return re.findall(r'<name><!\[CDATA\[(.*?)\]\]></name>', body)[:20] or \
               re.findall(r'<name>(.*?)</name>', body)[:20]
    j = json.loads(body)
    return [str(v.get('vod_name') or '') for v in (j.get('list') or [])][:20]


def classify(site):
    api, typ, name = str(site.get('api') or ''), site.get('type'), str(site.get('name') or '')
    name_hit = any(w in name.lower() for w in NAME_WORDS)
    try:
        titles = fetch_titles(api, typ)
    except Exception as e:
        return {**site, '_kind': 'unknown', '_err': type(e).__name__, '_rate': None}
    if not titles:
        return {**site, '_kind': 'unknown', '_err': 'no-titles', '_rate': None}
    hits = sum(1 for t in titles if any(w in t.lower() for w in CONTENT_WORDS))
    rate = hits / len(titles)
    # 收紧：>20% 直接判成人；10-20% 或站名命中且有命中 → 疑似，默认也排除
    if rate > 0.2 or (name_hit and rate > 0.05):
        kind = 'adult'
    elif rate > 0.1:
        kind = 'suspect'
    else:
        kind = 'clean'
    return {**site, '_kind': kind, '_rate': round(rate, 2), '_sample': len(titles)}


def main():
    sites = json.load(open(sys.argv[1]))
    out = [classify(s) for s in sites]
    clean = [s for s in out if s['_kind'] == 'clean']
    adult = [s for s in out if s['_kind'] == 'adult']
    unk = [s for s in out if s['_kind'] == 'unknown']
    print(f'正经 {len(clean)} / 成人 {len(adult)} / 未知 {len(unk)}\n')
    print(f'其中疑似 {len([x for x in out if x["_kind"]=="suspect"])} 个（10-20% 命中，默认排除）')
    print(f'\n正经站 Top 15（按片库）:')
    clean.sort(key=lambda x: -x.get('_total', 0))
    for s in clean[:15]:
        print(f"  {s.get('_total', 0):>8} 部  rate={s['_rate']}  {str(s['name'])[:20]}")
    json.dump(clean, open('sites_clean.json', 'w'), ensure_ascii=False, indent=1)
    print(f'\n合计正经片库 ≈ {sum(s.get("_total",0) for s in clean):,} 部')


if __name__ == '__main__':
    main()
