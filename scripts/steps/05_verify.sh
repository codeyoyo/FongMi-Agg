#!/bin/bash
# 05 三层验证 + 池合并：state/sites_clean.json → verify_result.json，池只增不减
source "$(dirname "$0")/_common.sh"
$PY -u pipeline/verify_clean.py state/sites_clean.json || exit 20
$PY - <<'PY'
import json, urllib.parse
def host(u):
    try: return (urllib.parse.urlparse(str(u)).hostname or '').lower()
    except Exception: return str(u)
vr={x['name']:x for x in json.load(open('state/verify_result.json'))}
clean={x['name']:x for x in json.load(open('state/sites_clean.json'))}
pool=json.load(open('state/sites_verified_pool.json'))
seen={host(s['api']) for s in pool}
add=[]
for n,x in vr.items():
    if all(x.get(k) for k in ('L1','L2','L3')):
        s=clean.get(n)
        if not s or host(s['api']) in seen: continue
        d=dict(s); d.setdefault('_src','old'); seen.add(host(s['api'])); pool.append(d); add.append(n)
json.dump(pool,open('state/sites_verified_pool.json','w'),ensure_ascii=False,indent=1)
full=sum(1 for x in vr.values() if all(x.get(k) for k in ('L1','L2','L3')))
print(f'三层全通 {full}/{len(vr)}；池 {len(pool)}（新增 {len(add)}）')
open('/tmp/ver_count.txt','w').write(f'{full} {len(vr)} {len(pool)} {len(add)}')
PY
read FULL TOT POOL ADD < /tmp/ver_count.txt
[ "$FULL" -gt 0 ] || { echo "!! 三层全通为 0，疑似出口网络问题，未覆盖池"; exit 20; }
counters "{\"pass\": $FULL, \"tested\": $TOT, \"pool\": $POOL, \"pool_added\": $ADD}"
exit 0
