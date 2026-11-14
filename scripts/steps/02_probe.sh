#!/bin/bash
# 02 测活：/tmp/zy_sites.json → state/ok_api.json
source "$(dirname "$0")/_common.sh"

[ -f /tmp/zy_sites.json ] || { echo "!! 缺 /tmp/zy_sites.json，先跑 01"; exit 30; }
[ -s /tmp/zy_sites.json ] || { echo "!! /tmp/zy_sites.json 为空"; exit 30; }

echo "--- probe_api"
$PY -u pipeline/probe_api.py /tmp/zy_sites.json || exit 20

$PY - <<'PY'
import json
try: ok=json.load(open('state/ok_api.json'))
except Exception: ok=[]
tot=sum(int(x.get('_total') or 0) for x in ok)
print(f'测活通过 {len(ok)}，合计 {tot:,} 部')
open('/tmp/probe_count.txt','w').write(f'{len(ok)} {tot}')
PY
read OK TOT < /tmp/probe_count.txt
[ "$OK" -gt 0 ] || { echo "!! 一个都没测通，疑似出口网络问题"; exit 20; }
counters "{\"ok\": $OK, \"total\": $TOT}"
exit 0
