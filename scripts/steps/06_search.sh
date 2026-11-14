#!/bin/bash
# 06 搜索测速：决定站点排序与 searchable 开关
source "$(dirname "$0")/_common.sh"
$PY pipeline/probe_search_time.py | tail -6 || exit 20
$PY - <<'PY'
import json
try: t=json.load(open('state/search_timing.json'))
except Exception: t=[]
print(f'搜索实测 {len(t)} 站')
open('/tmp/srch_count.txt','w').write(str(len(t)))
PY
read N < /tmp/srch_count.txt
counters "{\"tested\": $N}"
exit 0
