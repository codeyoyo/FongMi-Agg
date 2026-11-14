#!/usr/bin/env python3
"""把统一入口里带国别标记的直播频道测活后并入国际组。

只处理 intl_channels.json 覆盖不到的地域（马来西亚 / 新加坡 / 日本 等），
港澳台走 hktw 那条链路，不在这里重复。
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_live_routes import check
import concurrent.futures as cf

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WANT = {'my', 'sg', 'jp', 'th', 'ph', 'id', 'vn', 'in', 'gb', 'au', 'ca'}


def main():
    p = os.path.join(BASE, 'manual_live.json')
    if not os.path.exists(p):
        print('manual_live.json 不存在，跳过')
        return
    src = [x for x in json.load(open(p)) if x.get('cc') in WANT]
    if not src:
        print('没有需要补充的国别频道')
        return
    print(f'待测 {len(src)} 条')

    def one(x):
        ok, ms, _ = check(x['url'])
        return x, ok, ms

    with cf.ThreadPoolExecutor(12) as ex:
        res = list(ex.map(one, src))
    good = [dict(x, ms=ms) for x, ok, ms in res if ok]
    print(f'可播 {len(good)}/{len(src)}')
    json.dump(good, open(os.path.join(BASE, 'intl_extra.json'), 'w'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
