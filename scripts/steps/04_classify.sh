#!/bin/bash
# 04 内容分类：state/ok_api_final.json → state/sites_clean.json（正经站）+ 成人判定
source "$(dirname "$0")/_common.sh"
$PY pipeline/classify_sites.py state/ok_api_final.json || exit 20
$PY - <<'PY'
import json
try: c=json.load(open('state/sites_clean.json'))
except Exception: c=[]
try: a=json.load(open('state/ok_api_final.json'))
except Exception: a=[]
print(f'正经 {len(c)} / 全池 {len(a)}')
open('/tmp/cls_count.txt','w').write(f'{len(c)} {len(a)}')
PY
read CLEAN ALL < /tmp/cls_count.txt
[ "$CLEAN" -gt 0 ] || { echo "!! 分类后没有正经站"; exit 20; }
counters "{\"clean\": $CLEAN, \"pool\": $ALL}"
exit 0
