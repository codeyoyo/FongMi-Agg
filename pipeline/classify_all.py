#!/usr/bin/env python3
"""classify_all.py —— 对全量采集池跑成人/正经判定，输出每个站的 _kind

与 classify_sites.py 同一套判据，但：
  - 并发（本机海外出口，串行会拖到十分钟）
  - 输出全部结果到 kinds_all.json（含 adult / suspect / clean / unknown）
  - 抽样失败（超时/连不上）时用站名关键词兜底，避免 unknown 把成人站漏进正经组
"""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from classify_sites import classify, NAME_WORDS  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_pool():
    """与 build_modes.py 的 full 池同源：ok_api_final + clbug_clean（按 host 去重）"""
    from urllib.parse import urlparse

    def h(u):
        try:
            return (urlparse(str(u)).hostname or '').lower()
        except Exception:
            return str(u)

    pool, seen = [], set()
    for x in json.load(open(os.path.join(BASE, 'state', 'ok_api_final.json'))):
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
    return pool


def main():
    pool = load_pool()
    print(f'池：{len(pool)} 个采集站，开始并发分类…')
    with ThreadPoolExecutor(max_workers=8) as ex:
        out = list(ex.map(classify, pool))

    for s in out:
        if s.get('_kind') == 'unknown':
            nm = str(s.get('name') or '').lower()
            # 抽样失败：名字命中关键词的一律按成人处理（宁可多拦）
            s['_kind'] = 'adult' if any(w in nm for w in NAME_WORDS) else 'suspect-name'
            s['_fallback'] = 'name-only'

    from collections import Counter
    print('结果：', Counter(s['_kind'] for s in out))
    for s in sorted(out, key=lambda x: -x.get('_total', 0)):
        if s['_kind'] != 'clean':
            print(f"  {s['_kind']:<12} rate={s.get('_rate')} {str(s['name'])[:16]}")
    json.dump(out, open(os.path.join(BASE, 'state', 'kinds_all.json'), 'w'),
              ensure_ascii=False, indent=1)
    print('→ kinds_all.json')


if __name__ == '__main__':
    main()
