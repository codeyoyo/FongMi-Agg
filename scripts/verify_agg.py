#!/usr/bin/env python3
"""按 FongMi 真实调用顺序验证聚合站点（参数取自 app/.../api/SiteApi.java）

1) GET  /other                                   → homeContent，要 class
2) GET  /other?ac=detail&t=电影&pg=1              → categoryContent，要 list
3) GET  /other?ac=detail&ids=<vod_id>             → detailContent，要 play_url
4) GET  /other?wd=<词>&quick=true&extend=         → searchContent，要 list

用法: python3 verify_agg.py [host] [group]
"""
import json
import subprocess
import sys
import time
import urllib.parse

HOST = sys.argv[1] if len(sys.argv) > 1 else 'https://fm.le138.de5.net'
GROUP = sys.argv[2] if len(sys.argv) > 2 else 'other'
fails = []


def get(path):
    """用 curl 而不是 urllib：Cloudflare 对 urllib 的 TLS 指纹会 SSL EOF"""
    t0 = time.time()
    out = subprocess.run(
        ['curl', '-s', '-m', '90', '-A', 'okhttp/3.15.0', '-w', '\n%{http_code}', HOST + path],
        capture_output=True, timeout=120)
    txt = out.stdout.decode('utf-8', 'ignore')
    body, _, code = txt.rpartition('\n')
    return int(code or 0), body, time.time() - t0


def check(name, ok, detail):
    print(f"{'✅' if ok else '❌'} {name}: {detail}")
    if not ok:
        fails.append(name)


base = '/' + GROUP

# 1) 首页
try:
    st, body, ms = get(base)
    j = json.loads(body)
    cls = j.get('class') or []
    names = [c.get('type_name') for c in cls]
    check('1 首页分类表', st == 200 and len(cls) >= 2, f'{len(cls)} 个分类 {names} {ms:.1f}s')
except Exception as e:
    check('1 首页分类表', False, repr(e))
    names = []

# 2) 分类列表（FongMi 发 ac=detail + t + pg，无 ids）
tid = next((n for n in names if n not in ('全部',)), '电影')
try:
    st, body, ms = get(f'{base}?ac=detail&t={urllib.parse.quote(tid)}&pg=1')
    j = json.loads(body)
    lst = j.get('list') or []
    srcs = {str(x.get('vod_id', '')).split('|')[1] for x in lst[:0]}  # noqa: F841
    bad = [x for x in lst if not x.get('vod_id') or '|' not in str(x.get('vod_id'))]
    check('2 分类列表', st == 200 and len(lst) >= 10,
          f'分类={tid} 条数={len(lst)} 无源前缀={len(bad)} {ms:.1f}s')
except Exception as e:
    check('2 分类列表', False, repr(e))
    lst = []

# 3) 详情
if lst:
    vid = lst[0]['vod_id']
    try:
        st, body, ms = get(f'{base}?ac=detail&ids={urllib.parse.quote(vid)}')
        j = json.loads(body)
        one = (j.get('list') or [{}])[0]
        flags = str(one.get('vod_play_from') or '').split('$$$')
        urls = str(one.get('vod_play_url') or '').split('$$$')
        check('3 详情', bool(one) and bool(one.get('vod_play_url')),
              f'{one.get("vod_name")} 线路={len(flags)}/{len(urls)} 对齐={len(flags) == len(urls)} {ms:.1f}s')
        if flags and urls:
            print(f'     线路名: {flags[:4]}')
    except Exception as e:
        check('3 详情', False, repr(e))

# 4) 搜索
try:
    st, body, ms = get(f'{base}?wd={urllib.parse.quote("斗罗")}&quick=true&extend=')
    j = json.loads(body)
    lst2 = j.get('list') or []
    check('4 搜索', st == 200 and len(lst2) >= 1, f'条数={len(lst2)} {ms:.1f}s')
except Exception as e:
    check('4 搜索', False, repr(e))

print()
print('全部通过 ✅' if not fails else f'失败项: {fails}')
sys.exit(1 if fails else 0)
