#!/bin/bash
# 07 生成：clean/full/basic + adult/other + 聚合两站 + 多仓
source "$(dirname "$0")/_common.sh"

echo "--- build_modes"
$PY builders/build_modes.py || exit 30

echo "--- judge + build_groups"
$PY pipeline/judge.py >/dev/null 2>&1 && $PY builders/build_groups.py || echo "  !! 分组失败，沿用上一版"

if [ "${STEP07_FULL:-0}" = "1" ]; then
  echo "--- 国际组测活"
  $PY live/probe_intl.py 2>&1 | tail -3 || echo "  !! 国际组测活失败，沿用上一版"
  echo "--- 播放实测"
  $PY builders/play_probe.py >/dev/null 2>&1 || echo "  !! 播放实测失败，沿用上一版"
fi

echo "--- 聚合站点 + 多仓"
$PY builders/build_agg.py && $PY builders/build_two.py || echo "  !! 聚合站点失败，沿用上一版"
$PY builders/build_multi.py 2>&1 | tail -2 && cp dist/multi.json dist2/multi.json || echo "  !! 多仓失败，沿用上一版"

$PY - <<'PY'
import json
def n(f,key='sites'):
    try: return len(json.load(open(f)).get(key,[]))
    except Exception: return -1
c,f,b,m=n('dist2/clean.json'),n('dist2/full.json'),n('dist2/basic.json'),n('dist2/multi.json','urls')
print(f'clean {c} / full {f} / basic {b} / multi {m}')
open('/tmp/build_count.txt','w').write(f'{c} {f} {b} {m}')
PY
read C F B M < /tmp/build_count.txt
[ "$C" -gt 0 ] || { echo "!! clean.json 为 0"; exit 30; }
counters "{\"clean\": $C, \"full\": $F, \"basic\": $B, \"multi\": $M}"
exit 0
