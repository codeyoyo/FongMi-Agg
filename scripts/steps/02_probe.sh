#!/bin/bash
# 02 测活：state/tmp/zy_sites.json → state/ok_api.json
source "$(dirname "$0")/_common.sh"

[ -f state/tmp/zy_sites.json ] || { echo "!! 缺 state/tmp/zy_sites.json，先跑 01"; exit 30; }
[ -s state/tmp/zy_sites.json ] || { echo "!! state/tmp/zy_sites.json 为空"; exit 30; }

echo "--- probe_api"
"$PY" -u pipeline/probe_api.py state/tmp/zy_sites.json || exit 20

"$PY" - <<'PY'
import json
try: ok=json.load(open('state/ok_api.json'))
except Exception: ok=[]
tot=sum(int(x.get('_total') or 0) for x in ok)
print(f'测活通过 {len(ok)}，合计 {tot:,} 部')
open('state/tmp/probe_count.txt','w').write(f'{len(ok)} {tot}')
PY
read OK TOT < state/tmp/probe_count.txt
[ "$OK" -gt 0 ] || { echo "!! 一个都没测通，疑似出口网络问题"; exit 20; }
counters "{\"ok\": $OK, \"total\": $TOT}"
exit 0
