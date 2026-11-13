#!/usr/bin/env python3
"""make_sub.py —— 把测活结果组装成可发布的订阅目录

输入：
  dist/sites_js.json        build.py 产出的 js 源清单
  drpy/out/result.json      probe.mjs 产出的测活结果
  drpy/lib/*.js             drpy 引擎
  drpy/jscache/*.js         已缓存的规则文件
输出：
  dist2/  （fongmi.json + lib/ + js/）
"""
import json, os, re, shutil, sys

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE, 'dist2')
JS_SRC = os.environ.get('JS_CACHE') or os.path.join(BASE, 'drpy', 'jscache2')
RESULT = os.environ.get('RESULT_JSON') or os.path.join(BASE, 'drpy', 'out3', 'result.json')


def find_rule(fn):
    """规则文件按来源分目录存放，递归找第一个同名文件"""
    for root, _, files in os.walk(JS_SRC):
        if fn in files:
            return os.path.join(root, fn)
    return None

# 实测通过的纯 HTTP 采集站（build.py 的 stats 里 score>0 的也可以动态取，这里保留白名单兜底）
HTTP_OK = [
    {'name': '百度┃采集 [100]', 'type': 1, 'api': 'http://api.apibdzy.com/api.php/provide/vod/', 'searchable': 1, 'quickSearch': 1},
    {'name': '暴風┃采集 [100]', 'type': 1, 'api': 'http://bfzyapi.com/api.php/provide/vod/', 'searchable': 1, 'quickSearch': 1},
    {'name': '索尼┃采集 [100]', 'type': 1, 'api': 'http://suoniapi.com/api.php/provide/vod/', 'searchable': 1, 'quickSearch': 1},
    {'name': '非凡┃采集 [100]', 'type': 0, 'api': 'http://cj.ffzyapi.com/api.php/provide/vod/', 'searchable': 1, 'quickSearch': 1},
    {'name': '量子┃采集 [80]', 'type': 0, 'api': 'http://cj.lziapi.com/api.php/provide/vod/', 'searchable': 1, 'quickSearch': 1},
]

SKIP_WORDS = ('广告', '完全免费', '请勿相信')


def main():
    res_p = RESULT
    src_p = os.path.join(BASE, 'dist', 'sites_js.json')
    for p in (res_p, src_p):
        if not os.path.exists(p):
            print(f'缺输入: {p}')
            sys.exit(2)

    res = json.load(open(res_p))
    sites = json.load(open(src_p))
    ok = {r['name'] for r in res['results'] if r.get('score', 0) > 0}
    print(f'测活通过 {len(ok)}/{len(sites)}')

    for sub in ('', 'lib', 'js'):
        os.makedirs(os.path.join(DIST, sub), exist_ok=True)

    # 引擎
    for fn in ('drpy2.min.js', 'drpy-core-lite.min.js'):
        src = os.path.join(BASE, 'drpy', 'lib', fn)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(DIST, 'lib', fn))
        else:
            print(f'警告: 缺引擎 {fn}')

    out, seen, missing = [], set(), []
    for s in sites:
        if s.get('name') not in ok:
            continue
        if any(w in str(s.get('name') or '') for w in SKIP_WORDS):
            continue
        ext, api = str(s.get('ext') or ''), str(s.get('api') or '')
        if ext.startswith('http'):
            # 远程规则，无需打包文件
            item = {'name': s['name'], 'type': 3, 'api': './lib/drpy2.min.js', 'ext': ext}
        elif ext:
            # 本地规则，扩展名可能是 .js/.txt/.json
            fn = os.path.basename(ext.split('?')[0])
            src = find_rule(fn)
            if not src:
                missing.append((s['name'], fn)); continue
            shutil.copy(src, os.path.join(DIST, 'js', fn))
            item = {'name': s['name'], 'type': 3, 'api': './lib/drpy2.min.js', 'ext': f'./js/{fn}'}
        elif api.startswith('http'):
            item = {'name': s['name'], 'type': 3, 'api': api}
        else:
            continue
        if item['name'] in seen:
            continue
        seen.add(item['name']); out.append(item)

    for h in HTTP_OK:
        if h['name'] not in seen:
            seen.add(h['name']); out.append(h)

    cfg = {'sites': out}
    stats_p = os.path.join(BASE, 'dist', 'stats.json')
    if os.path.exists(stats_p):
        st = json.load(open(stats_p))
        # parses/flags 跨源合并后会大量重复，按关键字段去重
        if isinstance(st.get('parses'), list):
            seen_p, ps = set(), []
            for p in st['parses']:
                k = (str(p.get('name') or ''), str(p.get('url') or ''))
                if k in seen_p: continue
                seen_p.add(k); ps.append(p)
            if ps: cfg['parses'] = ps
        if isinstance(st.get('flags'), list):
            seen_f, fs_ = set(), []
            for f in st['flags']:
                k = str(f.get('name') if isinstance(f, dict) else f)
                if k in seen_f: continue
                seen_f.add(k); fs_.append(f)
            if fs_: cfg['flags'] = fs_
        if isinstance(st.get('doh'), list) and st['doh']:
            seen_d, ds = set(), []
            for d_ in st['doh']:
                k = str(d_.get('name') if isinstance(d_, dict) else d_)
                if k in seen_d: continue
                seen_d.add(k); ds.append(d_)
            if ds: cfg['doh'] = ds

    # parses/flags 从原始源续用（build.py 未落盘时走兜底）
    fb = os.path.join(BASE, 'fallback_parses.json')
    if 'parses' not in cfg and os.path.exists(fb):
        extra = json.load(open(fb))
        cfg.update({k: v for k, v in extra.items() if k not in cfg})

    json.dump(cfg, open(os.path.join(DIST, 'fongmi.json'), 'w'), ensure_ascii=False, indent=1)

    print(f'站点 {len(out)}（js {sum(1 for x in out if x["type"]==3 and x.get("ext"))}'
          f' / http {sum(1 for x in out if str(x.get("api","")).startswith("http"))}）')
    if missing:
        print(f'缺规则文件跳过 {len(missing)} 个: {[m[1] for m in missing][:6]}')
    print(f'输出 {DIST}')


if __name__ == '__main__':
    main()
