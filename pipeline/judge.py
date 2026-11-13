#!/usr/bin/env python3
"""judge.py —— 按站点自身分类名判定 正经 / 成人

判据：正规分类白名单命中数。正规采集站的分类固定是
电影/电视剧/连续剧/综艺/动漫/纪录片/动作片/喜剧片/爱情片/科幻片/…
命中 >= 3 个即视为正经影视站；否则视为成人站（成人站的分类是另一套词，
不会命中白名单）。

顺带修掉 probe_classes.py 里 type=0 (XML) 的 class 解析 bug：
应从 </list><class>…</class> 段里取 <ty> 文本，而不是全文正则。
"""
import json, os, re, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}

LEGIT = {
    '电影', '电影片', '电视剧', '连续剧', '剧集', '综艺', '综艺片', '动漫', '动漫片',
    '纪录片', '动作', '动作片', '喜剧', '喜剧片', '爱情', '爱情片', '科幻', '科幻片',
    '恐怖片', '剧情片', '战争片', '伦理片', '港台剧', '日韩剧', '欧美剧', '国产剧',
    '香港剧', '韩国剧', '日本剧', '台湾剧', '泰国剧', '马泰剧', '国产动漫', '日韩动漫',
    '欧美动漫', '港台动漫', '动漫电影', '短剧', '爽文短剧', '解说', '体育', '少儿',
    '资讯', '预告片', '专题片', '微电影', '经典片', '动画片',
}

# 抓取失败时只能按站名兜底：这些名字指向成人站（宁可多拦，不能漏进正经组）
ADULT_NAME_HINTS = ['番号', '奶', '大奶', '搜av', '杏吧', '仓库', '美少女', '香奶',
                    '黄av', '淫', '白嫖', '玉兔', '桃花', '滴滴']


def get_classes(site):
    api, typ = str(site.get('api') or ''), site.get('type')
    sep = '&' if '?' in api else '?'
    url = api + sep + ('ac=list&at=xml' if typ == 0 else 'ac=list')
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=12) as r:
            body = r.read(300000).decode('utf-8', 'ignore')
    except Exception as e:
        return {**site, '_classes': [], '_cerr': type(e).__name__}

    names = []
    if typ == 0:
        seg = re.search(r'<class>(.*?)</class>', body, re.S)
        text = seg.group(1) if seg else body
        names = re.findall(r'<ty[^>]*>([^<]*)</ty>', text)
    else:
        try:
            j = json.loads(body)
            for c in (j.get('class') or []):
                names.append(str(c.get('type_name') or '') if isinstance(c, dict) else str(c))
        except Exception as e:
            return {**site, '_classes': [], '_cerr': 'json:' + type(e).__name__}
    names = [n.strip() for n in names if str(n).strip()]
    return {**site, '_classes': names[:60]}


def judge(s):
    cls = s.get('_classes') or []
    # 子串匹配：分类名可能是 "动漫/海外动漫"、"爽文短剧" 这类复合名
    hit = sum(1 for c in cls if any(w in c for w in LEGIT))
    if hit >= 8:
        return {**s, '_kind': 'clean', '_legit_hits': hit}
    if cls:
        return {**s, '_kind': 'adult', '_legit_hits': hit}
    nm = str(s.get('name') or '').lower()
    kind = 'adult' if any(w in nm for w in ADULT_NAME_HINTS) else 'clean'
    return {**s, '_kind': kind, '_legit_hits': 0, '_fallback': 'name-only'}


def main():
    from urllib.parse import urlparse

    def h(u):
        try:
            return (urlparse(str(u)).hostname or '').lower()
        except Exception:
            return str(u)

    pool, seen = [], set()
    for x in json.load(open(os.path.join(BASE, 'ok_api_final.json'))):
        k = h(x['api'])
        if k in seen:
            continue
        seen.add(k)
        pool.append(x)
    for s in json.load(open(os.path.join(BASE, 'clbug_clean.json'))):
        k = h(s['api'])
        if k in seen:
            continue
        seen.add(k)
        pool.append({'name': s['name'].strip(), 'type': s['type'], 'api': s['api'],
                     '_total': s.get('total', 0), '_src': 'clbug'})

    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = [judge(x) for x in ex.map(get_classes, pool)]

    from collections import Counter
    print('判定：', Counter(r['_kind'] for r in rows))
    for r in sorted(rows, key=lambda x: -x.get('_total', 0)):
        flag = 'ADULT' if r['_kind'] == 'adult' else 'clean'
        print(f"  {flag:<6} legit={r.get('_legit_hits')} n={len(r.get('_classes') or [])} "
              f"{str(r['name'])[:18]} {r.get('_cerr', '')}")
    json.dump(rows, open(os.path.join(BASE, 'kinds2.json'), 'w'), ensure_ascii=False, indent=1)
    print('→ kinds2.json')


if __name__ == '__main__':
    main()
