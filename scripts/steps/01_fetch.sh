#!/bin/bash
# 01 拉源：zy.json + 统一入口 manual_sources.json → /tmp/zy_sites.json
source "$(dirname "$0")/_common.sh"

curl -sS -L -m 40 -o /tmp/zy.json \
  "https://raw.githubusercontent.com/hd9211/Tvbox1/main/zy.json" \
  || { echo "!! zy.json 拉取失败，沿用上次"; [ -f /tmp/zy.json ] || exit 20; }

echo "--- load_manual（统一入口）"
$PY -u pipeline/load_manual.py || exit 20

echo "--- 合并 manual 站点"
$PY - <<'PY' || exit 30
import json
d=json.load(open('/tmp/zy.json'))
s=[x for x in (d.get('sites') or d) if x.get('type') in (0,1) and str(x.get('api','')).startswith('http')]
try: m=json.load(open('state/manual_vod_sites.json'))
except Exception: m=[]
have={x['api'].rstrip('/') for x in s}
add=[x for x in m if x['api'].rstrip('/') not in have]
s += [{'name':x['name'],'api':x['api'],'type':x['type']} for x in add]
json.dump(s,open('/tmp/zy_sites.json','w'),ensure_ascii=False)
print(f'采集站 {len(s)}（manual 新增 {len(add)}）')
open('/tmp/zy_count.txt','w').write(f'{len(s)} {len(add)}')
PY

read TOTAL ADD < /tmp/zy_count.txt
counters "{\"sites\": $TOTAL, \"manual_added\": $ADD}"
exit 0
