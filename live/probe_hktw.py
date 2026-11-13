#!/usr/bin/env python3
"""港澳台频道实测：从 live_merged 找出同名频道的全部线路，逐条探活。

输出 hktw_tested.json：{展示名: {good: [{url, src, ms}], n_all, n_tested}}
build_live_config.py 会在第二轮据此收紧港澳台分组的线路。
"""
import json, os, sys, time, concurrent.futures as cf
from test_live_routes import check
from build_live_config import hk_base

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_PROBE = 12          # 每频道最多测多少条候选
WORKERS = 16


def probe(item):
    name, routes = item
    picks, per_src = [], {}
    for r in routes:
        s = r['src'].strip()
        if per_src.get(s, 0) >= 3:
            continue
        per_src[s] = per_src.get(s, 0) + 1
        picks.append(r)
        if len(picks) >= MAX_PROBE:
            break
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        res = list(ex.map(lambda r: (r, check(r['url'])), picks))
    good = sorted([(r, ms) for r, (ok, ms, _) in res if ok], key=lambda x: x[1])
    return name, {'n_all': len(routes), 'n_tested': len(picks),
                  'good': [{'url': r['url'], 'src': r['src'].strip(), 'ms': ms} for r, ms in good]}


if __name__ == '__main__':
    merged = json.load(open(os.path.join(BASE, 'live_merged.json')))
    groups = json.load(open(os.path.join(BASE, 'live_groups.json')))
    hk_group = next((g for g in groups if g['name'] == '港澳台'), None)
    if not hk_group:
        print('没有港澳台分组，先跑 build_live_config.py')
        sys.exit(1)

    # hk_base 归一 → 全部线路
    by_base = {}
    for key, routes in merged.items():
        for r in routes:
            by_base.setdefault(hk_base(r['name']), []).extend([r])

    want = {}
    for c in hk_group['channel']:
        b = hk_base(c['name'])
        if b in by_base:
            want[c['name']] = by_base[b]
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    want = dict(list(want.items())[:limit])
    print(f'待测 {len(want)} 个港澳台频道，每频道最多 {MAX_PROBE} 线', flush=True)

    OUTP = os.path.join(BASE, 'hktw_tested.json')
    out = {}
    if os.path.exists(OUTP):
        try:
            out = json.load(open(OUTP))
        except Exception:
            out = {}
    todo = {k: v for k, v in want.items() if k not in out}
    print(f'已完成 {len(out)}，本轮 {len(todo)}', flush=True)

    t0 = time.time()
    for i, item in enumerate(todo.items(), 1):
        name, res = probe(item)
        out[name] = res
        if i % 4 == 0 or i == len(todo):
            alive = sum(1 for v in out.values() if v['good'])
            print(f'  {i}/{len(todo)}  累计可播频道 {alive}  {time.time()-t0:.0f}s', flush=True)
            json.dump(out, open(OUTP, 'w'), ensure_ascii=False, indent=1)

    json.dump(out, open(OUTP, 'w'), ensure_ascii=False, indent=1)
    dead = [k for k, v in out.items() if not v['good']]
    print(f'\n完成 {len(out)} 频道，可播 {len(out)-len(dead)}，全死 {len(dead)}，耗时 {time.time()-t0:.0f}s')
    if dead:
        print('全死：', dead[:25])
