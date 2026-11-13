#!/usr/bin/env python3
"""批量实测 live_merged 里所有打包频道的线路，输出「每频道可用线路」表"""
import json, os, sys, time, concurrent.futures as cf
from test_live_routes import check

BASE = os.path.dirname(os.path.abspath(__file__))
MAX_PROBE = 14          # 每频道最多测多少条候选线路


def probe_channel(item):
    key, routes = item
    picks, seen_src = [], {}
    for r in routes:
        s = r['src'].strip()
        if seen_src.get(s, 0) >= 3:
            continue
        seen_src[s] = seen_src.get(s, 0) + 1
        picks.append(r)
        if len(picks) >= MAX_PROBE:
            break
    with cf.ThreadPoolExecutor(14) as ex:
        res = list(ex.map(lambda r: (r, check(r['url'])), picks))
    good = sorted([(r, ms) for r, (ok, ms, _) in res if ok], key=lambda x: x[1])
    return key, {'n_all': len(routes), 'n_tested': len(picks),
                 'good': [{'url': r['url'], 'src': r['src'].strip(), 'ms': ms} for r, ms in good]}


if __name__ == '__main__':
    merged = json.load(open(os.path.join(BASE, 'live_merged.json')))
    groups = json.load(open(os.path.join(BASE, 'live_groups.json')))

    # 只测打包进配置的频道：用归一名反查 merged
    from build_live_config import canon
    want = {}
    for g in groups:
        for c in g['channel']:
            ck = canon(c['name'])
            if ck in merged:
                want[ck] = merged[ck]

    scope = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if scope == 'core':
        core = set()
        for g in groups[:2]:
            for c in g['channel']:
                core.add(canon(c['name']))
        want = {k: v for k, v in want.items() if k in core}

    # 断点续测
    OUTP = os.path.join(BASE, 'live_route_test_all.json')
    out = {}
    if os.path.exists(OUTP):
        try:
            out = json.load(open(OUTP))
        except Exception:
            out = {}
    todo = {k: v for k, v in want.items() if k not in out}
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 9999
    todo = dict(list(todo.items())[:limit])
    print(f'总 {len(want)} 频道，已完成 {len(out)}，本轮测 {len(todo)}，最多 {MAX_PROBE} 线/频道', flush=True)
    t0 = time.time()
    done = 0
    for item in todo.items():
        k, v = probe_channel(item)
        out[k] = v
        done += 1
        if done % 5 == 0 or done == len(todo):
            alive = sum(1 for x in out.values() if x['good'])
            print(f'  {done}/{len(todo)}  累计可用 {alive} 个  {time.time()-t0:.0f}s', flush=True)
            json.dump(out, open(os.path.join(BASE, 'live_route_test_all.json'), 'w'),
                      ensure_ascii=False, indent=1)

    json.dump(out, open(os.path.join(BASE, 'live_route_test_all.json'), 'w'), ensure_ascii=False, indent=1)
    dead = [k for k, v in out.items() if not v['good']]
    print(f'\n本轮完成 {len(todo)}，累计 {len(out)} 频道，可用 {len(out)-len(dead)}，全死 {len(dead)}，耗时 {time.time()-t0:.0f}s')
    if dead:
        print('全死频道:', [merged[k][0]['name'] for k in dead[:20]])
