#!/bin/sh
# finalize_live.sh —— 等实测数据齐了，重建直播聚合并部署
set -e
cd "$(dirname "$0")"

echo "=== 实测数据状态"
python3 - <<'PY'
import json, os
p = 'live_route_test_all.json'
if not os.path.exists(p):
    print('  尚未生成'); raise SystemExit(1)
d = json.load(open(p))
g = sum(1 for v in d.values() if v.get('good'))
print(f'  {len(d)} 频道已测，{g} 个有可用线路')
n = sum(len(v['good']) for v in d.values())
print(f'  可用线路总数 {n}')
PY

echo "=== 重建直播分组（只留实测通过线路）"
python3 build_live_config.py

echo "=== 生成配置"
python3 build_modes.py

echo "=== 部署"
bash deploy_pages.sh 2>&1 | tail -5
