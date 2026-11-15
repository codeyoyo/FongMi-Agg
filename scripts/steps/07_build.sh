#!/bin/bash
# 07 生成：clean/full/basic + adult/other + 聚合两站 + 多仓
source "$(dirname "$0")/_common.sh"

echo "--- build_modes"
"$PY" builders/build_modes.py || exit 30

echo "--- judge + build_groups"
"$PY" pipeline/judge.py >/dev/null 2>&1 && "$PY" builders/build_groups.py || echo "  !! 分组失败，沿用上一版"

if [ "${STEP07_FULL:-0}" = "1" ]; then
  echo "--- 国际组测活"
  "$PY" live/probe_intl.py 2>&1 | tail -3 || echo "  !! 国际组测活失败，沿用上一版"
  echo "--- 播放实测"
  "$PY" builders/play_probe.py >/dev/null 2>&1 || echo "  !! 播放实测失败，沿用上一版"
fi

echo "--- 聚合站点 + 多仓"
"$PY" builders/build_agg.py && "$PY" builders/build_two.py || echo "  !! 聚合站点失败，沿用上一版"
if [ "${STEP07_MULTI:-1}" = "1" ]; then
  echo "--- 多仓"
  "$PY" builders/build_multi.py 2>&1 | tail -2 && cp dist/multi.json dist2/multi.json || echo "  !! 多仓失败，沿用上一版"
fi

"$PY" - <<'PY' || exit 30
import json, os
cfg = json.load(open('config/artifacts.json', encoding='utf-8'))
files = [a.get('file') or (a['id'] + '.json') for a in (cfg.get('artifacts') or []) if a.get('enabled', True)]
counts, missing = {}, []
for f in files:
    # 产物名只允许纯 .json 文件名，避免读出 dist2 之外
    if os.path.basename(f) != f or not f.endswith('.json'):
        missing.append(f)
        continue
    p = os.path.join('dist2', f)
    if not os.path.isfile(p):
        missing.append(f)
        continue
    try:
        d = json.load(open(p, encoding='utf-8'))
        counts[f] = len(d.get('sites') or d.get('urls') or [])
    except Exception:
        counts[f] = -1
print('产物:', ', '.join(f'{f}={n}' for f, n in counts.items()))
bad = [f for f, n in counts.items() if n <= 0]
if missing or bad:
    print('!! 产物缺失或为空:', missing + bad)
    raise SystemExit(30)
print('##COUNTERS## ' + json.dumps({'artifacts': counts}, ensure_ascii=False))
PY
exit 0
