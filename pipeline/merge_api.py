#!/usr/bin/env python3
"""merge_api.py —— 把实测采集站合并进订阅，生成精简版和完整版"""
import json, os, shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(BASE, 'dist2')
api = json.load(open(os.path.join(BASE, 'ok_api_final.json')))
base_cfg = json.load(open(os.path.join(DIST, 'fongmi.json')))

js_sites = [s for s in base_cfg['sites'] if s.get('ext')]  # 96 个 js 源
# 原先手测的 5 个采集站也保留（可能在 Top N 之外）
old_http = [s for s in base_cfg['sites'] if str(s.get('api', '')).startswith('http')]
old_apis = {str(s['api']).rstrip('/') for s in old_http}


def to_site(x):
    return {
        'name': f"{x['name']} [{x['_total']//10000}万]",
        'type': x['type'],
        'api': x['api'],
        'searchable': 1,
        'quickSearch': 1,
    }


def build(n_api, fname):
    picked = [to_site(x) for x in api[:n_api]]
    # 补上原 5 个手测站中未被覆盖的
    have = {str(x['api']).rstrip('/') for x in api[:n_api]}
    for s in old_http:
        if str(s['api']).rstrip('/') not in have:
            picked.append(s)
    cfg = {'sites': picked + js_sites}
    for k in ('parses', 'flags', 'doh'):
        if base_cfg.get(k):
            cfg[k] = base_cfg[k]
    json.dump(cfg, open(os.path.join(DIST, fname), 'w'), ensure_ascii=False, indent=1)
    total = sum(x['_total'] for x in api[:n_api])
    print(f'{fname}: {len(cfg["sites"])} 站点（{n_api} 采集 + {len(js_sites)} js）片库 ≈ {total:,}')
    return len(cfg['sites'])


# 精简版：Top 20 采集站，搜索快
build(20, 'fongmi.json')
# 完整版：全部 56 个
build(56, 'fongmi-full.json')

# 统计
for f in ('fongmi.json', 'fongmi-full.json'):
    d = json.load(open(os.path.join(DIST, f)))
    print(f'  {f} 体积 {os.path.getsize(os.path.join(DIST, f))} B')
