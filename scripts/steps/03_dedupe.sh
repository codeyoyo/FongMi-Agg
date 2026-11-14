#!/bin/bash
# 03 去重：state/ok_api.json → state/ok_api_final.json（同域名留最强，同片库去重）
source "$(dirname "$0")/_common.sh"

$PY - <<'PY' || exit 30
import json, urllib.parse
from collections import defaultdict
ok=json.load(open('state/ok_api.json'))
byhost=defaultdict(list)
for s in ok:
    byhost[urllib.parse.urlparse(s['api']).netloc.lower()].append(s)
best=[]
for h,lst in byhost.items():
    lst.sort(key=lambda x:(x.get('_total',0),1 if x.get('type')==1 else 0),reverse=True)
    best.append(lst[0])
best.sort(key=lambda x:(-x.get('_total',0),0 if x.get('type')==1 else 1))
seen,uniq=set(),[]
for x in best:
    t=x.get('_total',0)
    if t and t in seen: continue
    if t: seen.add(t)
    uniq.append(x)
json.dump(uniq,open('state/ok_api_final.json','w'),ensure_ascii=False,indent=1)
tot=sum(int(x.get('_total') or 0) for x in uniq)
print(f'独立源 {len(uniq)}，合计 {tot:,} 部')
open('/tmp/dedupe_count.txt','w').write(f'{len(uniq)} {tot}')
PY
read N TOT < /tmp/dedupe_count.txt
counters "{\"unique\": $N, \"total\": $TOT}"
exit 0
