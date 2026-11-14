#!/usr/bin/env python3
"""build_modes.py —— 生成两个版本的订阅
  clean.json  家里电视用：只含正经影视站
  full.json   自己用：全量
两者都带 96 个 js 源（规则文件来自公开配置，不涉及内容分级）
"""
import json, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(BASE, 'dist2')

base_cfg = json.load(open(os.path.join(BASE, 'backup', 'fongmi-pre-mode.json')))
_jsp = os.path.join(BASE, 'dist2', 'fongmi.json')
if os.path.exists(_jsp):
    try:
        js_sites = [s for s in json.load(open(_jsp)).get('sites', []) if s.get('ext') or s.get('type') == 3]
    except Exception:
        js_sites = [s for s in base_cfg['sites'] if s.get('ext')]
else:
    js_sites = [s for s in base_cfg['sites'] if s.get('ext')]
extra = {k: v for k, v in base_cfg.items() if k != 'sites'}

all_api = json.load(open(os.path.join(BASE, 'state', 'ok_api_final.json')))

# 全量版也并入 clbug 池（已测活通过的）
try:
    from urllib.parse import urlparse as _up
    def _h(u):
        try: return (_up(str(u)).hostname or '').lower()
        except Exception: return str(u)
    _seen = {_h(x['api']) for x in all_api}
    _add = 0
    for _s in json.load(open(os.path.join(BASE, 'clbug_clean.json'))):
        if _h(_s['api']) in _seen:
            continue
        _seen.add(_h(_s['api']))
        all_api.append({'name': _s['name'].strip(), 'type': _s['type'],
                        'api': _s['api'], '_total': _s['total'], '_src': 'clbug'})
        _add += 1
    print(f'  full 池并入 clbug: +{_add} → {len(all_api)} 个')
except FileNotFoundError:
    pass
# clean 池：sites_verified_pool.json = 旧池三层全通 + clbug 池三层全通，已去重
_pool_file = os.path.join(BASE, 'state', 'sites_verified_pool.json')
if os.path.exists(_pool_file):
    clean_api = json.load(open(_pool_file))
    print(f'  clean 池: {len(clean_api)} 个（已验证三层全通，含 clbug 新站）')
else:
    clean_api = json.load(open(os.path.join(BASE, 'state', 'sites_clean.json')))
    vr = {x['name']: x for x in json.load(open(os.path.join(BASE, 'state', 'verify_result.json')))}
    before = len(clean_api)
    clean_api = [x for x in clean_api
                 if all((vr.get(x['name']) or {}).get(k) for k in ('L1', 'L2', 'L3'))]
    print(f'  三层过滤: {before} → {len(clean_api)}')
clean_apis = {str(x['api']) for x in clean_api}


# 搜索实测结果：能搜到的按耗时排序，搜不到的关掉 searchable
try:
    _timing = {r['name']: r for r in json.load(open(os.path.join(BASE, 'state', 'search_timing.json')))}
except FileNotFoundError:
    _timing = {}


def _make_key(x):
    """FongMi Site.key 为必要字段，需全局唯一"""
    import hashlib
    raw = (str(x.get('api', '')) + '|' + str(x.get('ext', '')) + '|' + str(x.get('name', '')))
    return 'k' + hashlib.md5(raw.encode()).hexdigest()[:10]


def search_rank(x):
    """排序键：能搜到的在前，且按耗时升序"""
    t = _timing.get(x['name']) or {}
    if t.get('n', 0) > 0:
        return (0, t.get('ms', 9999))
    return (1, 9999)


def to_site(x):
    t = _timing.get(x['name']) or {}
    can_search = 1 if t.get('n', 0) > 0 else (1 if not _timing else 0)
    return {
        'key': _make_key(x),
        'name': f"{x['name']} [{x['_total'] // 10000}万]",
        'type': x['type'],
        'api': x['api'],
        'searchable': can_search,
        'quickSearch': can_search,
    }


def normalize_js(site):
    """js 源补 searchable/quickSearch —— 缺这两个字段 FongMi 搜索会直接跳过"""
    s = dict(site)
    s.setdefault('key', _make_key(site))
    s.setdefault('searchable', 1)
    s.setdefault('quickSearch', 1)
    return s


# 直播：聚合为单一分组，每频道挂多线路由 FongMi 自动 fallback
# （不再是 10 个独立源让用户自己切换）
try:
    _lg = json.load(open(os.path.join(BASE, 'state', 'live_groups.json')))
    LIVES = [{'name': '聚合直播', 'groups': _lg}]
    print('  直播: 聚合 %d 个分组 / %d 个频道（每频道多线路自动切换）'
          % (len(_lg), sum(len(g['channel']) for g in _lg)))
except FileNotFoundError:
    LIVES = [{'name': '聚合直播', 'url':
              'https://cdn.jsdelivr.net/gh/Guovin/iptv-api@gd/output/result.m3u'}]


def build(pool, fname, label):
    pool = sorted(pool, key=search_rank)
    sites = [to_site(x) for x in pool] + [normalize_js(x) for x in js_sites]
    cfg = {'sites': sites, 'lives': LIVES}
    cfg.update(extra)

    # 去重（同名/同 api）
    seen, out = set(), []
    for s in cfg['sites']:
        k = (s.get('name'), str(s.get('api')))
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    cfg['sites'] = out

    p = os.path.join(DIST, fname)
    json.dump(cfg, open(p, 'w'), ensure_ascii=False, indent=1)
    total = sum(x.get('_total', 0) for x in pool)
    print(f'{label:6} {fname:14} 站点 {len(out):>3}（采集 {len(pool)} + js {len(js_sites)}）'
          f'  片库 ≈ {total:,}  文件 {os.path.getsize(p)} B')


build(clean_api, 'clean.json', '干净版')
build(all_api, 'full.json', '全量版')

# basic：只有采集站，不含 js 源 —— 排查搜索慢/结果少用
_saved = globals()['js_sites']
globals()['js_sites'] = []
build(clean_api, 'basic.json', '极简版')
globals()['js_sites'] = _saved

# 旧文件清掉，避免混淆
for old in ('fongmi-full.json',):
    p = os.path.join(DIST, old)
    if os.path.exists(p):
        os.remove(p)
        print(f'  已移除旧文件 {old}')
