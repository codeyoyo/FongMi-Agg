#!/bin/sh
# daily_clbug.sh —— 从 tvbox.clbug.com 拉取全部订阅源，筛出优质采集站并合并进主池
# 用法: sh scripts/daily_clbug.sh
set -e
cd "$(dirname "$0")/.."

echo "=== [1/5] 抓取 tvbox.clbug.com 源清单"
curl -sL -m 40 -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0" \
     "https://tvbox.clbug.com/user.php" -o /tmp/clbug.html
python3 - <<'PY'
import re, html, json
s = open('/tmp/clbug.html', encoding='utf-8', errors='ignore').read()
rows = re.findall(r'<tr[\s\S]*?</tr>', s, re.I)
out = []
for r in rows:
    tds = re.findall(r'<td[\s\S]*?</td>', r, re.I)
    cells = [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', t))).strip() for t in tds]
    if len(cells) >= 3 and cells[2].startswith('http'):
        out.append({'cells': cells, 'urls': [cells[2]]})
json.dump(out, open('/tmp/rows.json', 'w'), ensure_ascii=False)
print(f'  源清单 {len(out)} 条')
PY

echo "=== [2/5] 并发拉取各源配置"
python3 clbug/fetch_clbug.py | head -4

echo "=== [3/5] 采集站测活"
python3 clbug/probe_clbug.py | head -4

echo "=== [4/5] 成人过滤 + 三层验证"
python3 clbug/verify_clbug.py | head -4

echo "=== [5/5] 合并进主池"
python3 - <<'PY'
import json
from urllib.parse import urlparse
def host(u):
    try: return (urlparse(u).hostname or '').lower()
    except Exception: return ''
vr = {x['name']: x for x in json.load(open('state/verify_result.json'))}
old = [x for x in json.load(open('state/sites_clean.json'))
       if all((vr.get(x['name']) or {}).get(k) for k in ('L1','L2','L3'))]
new = [{'name': s['name'].strip(), 'type': s['type'], 'api': s['api'],
        '_total': s['total'], '_src': 'clbug'} for s in json.load(open('clbug_clean.json'))]
pool, seen = [], set()
for s in old + new:
    s = dict(s); s.setdefault('_src', 'old')
    h = host(s['api'])
    if h in seen: continue
    seen.add(h); pool.append(s)
json.dump(pool, open('state/sites_verified_pool.json','w'), ensure_ascii=False, indent=1)
print(f'  合并池 {len(pool)} 个站，片库 ≈ {sum(int(s.get("_total") or 0) for s in pool)} 部')
PY

echo "=== 完成，下一步: python3 builders/build_modes.py && bash scripts/deploy_pages.sh"
