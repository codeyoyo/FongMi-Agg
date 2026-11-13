#!/usr/bin/env python3
"""build_two.py —— 生成"只有两个站点"的配置 two.json

sites 里就两条：
  影视资源  → /other   （正经采集站，按分类桶在服务端聚合）
  成人资源  → /adult   （25 个成人采集站，同）

两条都是 type:1（纯 HTTP 采集协议），FongMi 原生支持，设备端零依赖。
"""
import json, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(BASE, 'dist2')
HOST = 'https://fm.le138.de5.net'

try:
    LIVES = [{'name': '聚合直播', 'groups': json.load(open(os.path.join(BASE, 'live_groups.json')))}]
except FileNotFoundError:
    LIVES = []


def site(key, name, path):
    return {
        'key': key,
        'name': name,
        'type': 1,
        'api': HOST + path,
        'ext': '',
        'searchable': 1,
        'quickSearch': 1,
    }


cfg = {
    'sites': [
        site('agg_other', '影视资源', '/other'),
        site('agg_adult', '成人资源', '/adult'),
    ],
    'lives': LIVES,
}

p = os.path.join(DIST, 'two.json')
json.dump(cfg, open(p, 'w'), ensure_ascii=False, indent=1)
print('two.json 站点', len(cfg['sites']), '大小', os.path.getsize(p), 'B')
