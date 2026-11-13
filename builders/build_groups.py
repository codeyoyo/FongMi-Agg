#!/usr/bin/env python3
"""build_groups.py —— 把 sites 拆成两个「组」（两份配置，FongMi 原生唯一可行的分组形态）

  other.json  其它：正经影视采集站 + 全部 js 源
  adult.json  成人资源：按内容分类判定的成人采集站

FongMi 的 Site 数据模型没有 group 字段（bean/Site.java），sites 数组是扁平列表，
App 里不存在"站点分组"。所以"两个组"落地为两份配置：用户在 FongMi 的配置里
选哪一个，就是哪一组。两份都带同一套聚合直播。
"""
import json, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(BASE, 'dist2')

kinds = json.load(open(os.path.join(BASE, 'kinds2.json')))
js_sites = [s for s in json.load(open(os.path.join(BASE, 'backup', 'fongmi-pre-mode.json')))['sites']
            if s.get('ext')]

try:
    _timing = {r['name']: r for r in json.load(open(os.path.join(BASE, 'search_timing.json')))}
except FileNotFoundError:
    _timing = {}

try:
    _lg = json.load(open(os.path.join(BASE, 'live_groups.json')))
    LIVES = [{'name': '聚合直播', 'groups': _lg}]
except FileNotFoundError:
    LIVES = []


def make_key(x):
    import hashlib
    raw = str(x.get('api', '')) + '|' + str(x.get('ext', '')) + '|' + str(x.get('name', ''))
    return 'k' + hashlib.md5(raw.encode()).hexdigest()[:10]


def rank(x):
    """优选排序：片库量大在前（用户关心的"优选"= 内容多），可搜性次要。"""
    t = _timing.get(x['name']) or {}
    searchable = 0 if t.get('n', 0) > 0 else 1
    return (-int(x.get('_total') or 0), searchable, t.get('ms', 9999))


def to_site(x, force_search=False):
    t = _timing.get(x['name']) or {}
    can = 1 if force_search else (1 if t.get('n', 0) > 0 else (1 if not _timing else 0))
    total = int(x.get('_total') or 0)
    label = f"{x['name']} [{total // 10000}万]" if total >= 10000 else x['name']
    return {'key': make_key(x), 'name': label, 'type': x['type'], 'api': x['api'],
            'searchable': can, 'quickSearch': can}


def norm_js(s):
    s = dict(s)
    s.setdefault('key', make_key(s))
    s.setdefault('searchable', 1)
    s.setdefault('quickSearch', 1)
    return s


def dump(sites, fname, label):
    seen, out = set(), []
    for s in sites:
        k = (s.get('name'), str(s.get('api')))
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    cfg = {'sites': out, 'lives': LIVES}
    p = os.path.join(DIST, fname)
    json.dump(cfg, open(p, 'w'), ensure_ascii=False, indent=1)
    print(f'{label:<10} {fname:<12} 站点 {len(out):>3}  文件 {os.path.getsize(p)} B')


adult = sorted([x for x in kinds if x['_kind'] == 'adult'], key=rank)
clean = sorted([x for x in kinds if x['_kind'] == 'clean'], key=rank)

dump([to_site(x, force_search=True) for x in adult], 'adult.json', '成人资源组')
dump([to_site(x) for x in clean] + [norm_js(s) for s in js_sites], 'other.json', '其它组')
