#!/usr/bin/env python3
"""国际组每日测活：intl_channels.json 里的频道逐条探活，死的剔除。

这些源（iptv-org 的 us/jp/kr/sg）属「短时可用」性质，实测一轮就能掉一半，
必须每天重测，否则清单里会堆满死频道。

安全阀：本次存活数 < MIN_KEEP 时不动原文件——防止一次网络故障把整组清空。
"""
import json, os, sys, time, concurrent.futures as cf
from test_live_routes import check

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(BASE, 'config', 'intl_channels.json')
WORKERS = 14
MIN_KEEP = 10          # 存活少于这个数就认为是网络问题，不清空


def probe(x):
    ok, ms, note = check(x['url'])
    return x, ok, ms


if __name__ == '__main__':
    if not os.path.exists(PATH):
        print('没有 intl_channels.json，跳过')
        sys.exit(0)
    data = json.load(open(PATH))
    print(f'国际组测活：{len(data)} 个频道', flush=True)

    t0 = time.time()
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        res = list(ex.map(probe, data))
    alive = [x for x, ok, _ in res if ok]
    dead = [x['name'] for x, ok, _ in res if not ok]

    print(f'存活 {len(alive)}/{len(data)}，耗时 {time.time()-t0:.0f}s')
    if dead:
        print('失效:', ', '.join(dead[:15]) + (' ...' if len(dead) > 15 else ''))

    if len(alive) < MIN_KEEP:
        print(f'⚠ 存活 {len(alive)} < {MIN_KEEP}，疑似网络故障，保留原文件不动')
        sys.exit(0)

    json.dump(alive, open(PATH, 'w'), ensure_ascii=False, indent=1)
    print(f'已写回 {len(alive)} 条')
