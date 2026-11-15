#!/usr/bin/env python3
"""build_modes.py —— 生成两个版本的订阅
  clean.json  家里电视用：只含正经影视站
  full.json   自己用：全量
两者都带 96 个 js 源（规则文件来自公开配置，不涉及内容分级）
"""
import json, os
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(BASE, 'dist2')
os.makedirs(DIST, exist_ok=True)

# 旧版基线配置（js 源 + parsers/flags 等顶层字段）。容器里有，空 clone 没有；
# 缺失时用空基线继续，至少能生成采集站/聚合站产物，不直接崩。
try:
    base_cfg = json.load(open(os.path.join(BASE, 'backup', 'fongmi-pre-mode.json'), encoding='utf-8'))
except FileNotFoundError:
    base_cfg = {'sites': []}
    print('  !! 缺 backup/fongmi-pre-mode.json：js 源与顶层扩展字段留空')
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
    for _s in json.load(open(os.path.join(BASE, 'debug', 'clbug_clean.json'))):
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


TYPE_LABELS = {'list': '直连列表', 'agg_movie': '聚合站·影视', 'agg_adult': '聚合站·成人'}
VALID_TYPES = tuple(TYPE_LABELS)


def artifact_types(a):
    """产物包含哪些输出类型。新格式用 types 数组；旧格式 type/group 自动兼容。"""
    t = a.get('types')
    if isinstance(t, list):
        return [x for x in t if x in VALID_TYPES]
    if a.get('type') == 'agg':
        return ['agg_adult' if (a.get('group') or 'movie') == 'adult' else 'agg_movie']
    return ['list']


def build_artifact(a):
    """一个产物可以同时含多种类型：聚合站（影视/成人）各挂一条 site，
    直连列表按 pool 取站点并可选并入 js 源。整份配置写进 a['file']。"""
    aid = a['id']
    label = a.get('name') or aid
    types = artifact_types(a)
    if not types:
        print(f"  !! 产物 {aid} 没有选类型，跳过")
        return

    # 安全检查：产物文件名只允许 dist2 下的普通 .json 文件名
    fname = str(a.get('file') or (aid + '.json'))
    dist_root = os.path.realpath(DIST)
    outp = os.path.realpath(os.path.join(dist_root, fname))
    if (os.path.basename(fname) != fname
            or not fname.endswith('.json')
            or os.path.commonpath([dist_root, outp]) != dist_root):
        print(f"  !! 产物 {aid} 的 file 非法，跳过：{fname!r}")
        return

    sites = []

    # 聚合站：一个类型一条 site，指向 worker 的对应组端点
    agg_types = [t for t in types if t.startswith('agg_')]
    for t in agg_types:
        group = t.split('_', 1)[1]
        name = label if len(agg_types) == 1 else label + '·' + ('影视' if group == 'movie' else '成人')
        sites.append({'name': name, 'type': 1,
                      'api': f'{AGG_BASE}/{group}?m={aid}',
                      'searchable': 1, 'quickSearch': 1, 'filterable': 0})

    # 直连列表：按 pool 取站点，可选并入 js 源
    if 'list' in types:
        pool_get = POOLS.get(a.get('pool', 'clean'))
        if not pool_get:
            print(f"  !! 产物 {aid} 的 pool={a.get('pool')} 不认识，跳过列表部分")
        else:
            pool = sorted(pool_get(), key=search_rank)
            sites += [to_site(x) for x in pool]
            if a.get('include_js', True):
                sites += [normalize_js(x) for x in js_sites]

    cfg = {'sites': sites, 'lives': LIVES if a.get('lives', True) else []}
    # categories 是 Site 级字段，写到 VodConfig 顶层客户端不读，别在这里加。
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

    json_text = json.dumps(cfg, ensure_ascii=False, indent=1)
    Path(outp).write_text(json_text, encoding='utf-8')
    print(f"{label:6} {fname:14} 类型 {'+'.join(TYPE_LABELS[t] for t in types):<18}"
          f" 站点 {len(out):>3}  文件 {os.path.getsize(outp)} B")


# ---------- 产物定义（可自定义） ----------
DEFAULT_ARTS = [
    {'id': 'clean', 'file': 'clean.json', 'name': '干净版', 'types': ['list'], 'pool': 'clean',
     'include_js': True, 'lives': True, 'buckets': 'all', 'enabled': True},
    {'id': 'full', 'file': 'full.json', 'name': '全量版', 'types': ['list'], 'pool': 'full',
     'include_js': True, 'lives': True, 'buckets': 'all', 'enabled': True},
    {'id': 'basic', 'file': 'basic.json', 'name': '极简版', 'types': ['list'], 'pool': 'clean',
     'include_js': False, 'lives': True, 'buckets': 'all', 'enabled': True},
]
ART_FILE = os.environ.get('FONGMI_ARTIFACTS') or os.path.join(BASE, 'config', 'artifacts.json')


def load_artifacts():
    if not os.path.exists(ART_FILE):
        print('  产物：用内置三件套（无 config/artifacts.json）')
        return DEFAULT_ARTS
    try:
        cfg = json.load(open(ART_FILE, encoding='utf-8'))
        arts = [a for a in (cfg.get('artifacts') or []) if a.get('enabled', True)]
        if not arts:
            raise ValueError('artifacts 为空')
        try:
            shown = os.path.relpath(ART_FILE, BASE)
        except ValueError:
            shown = ART_FILE
        print(f'  产物：使用 {shown}（{len(arts)} 个）')
        return arts
    except Exception as e:
        print(f'  !! artifacts.json 读取失败，用内置三件套：{e}')
        return DEFAULT_ARTS


POOLS = {'clean': lambda: clean_api, 'full': lambda: all_api}

AGG_BASE = os.environ.get('FONGMI_AGG_BASE', 'https://fm.le138.de5.net')


for _a in load_artifacts():
    build_artifact(_a)

# 旧文件清掉，避免混淆
for old in ('fongmi-full.json',):
    p = os.path.join(DIST, old)
    if os.path.exists(p):
        os.remove(p)
        print(f'  已移除旧文件 {old}')
