#!/bin/sh
# run.sh —— FongMi 订阅全流程：采集 → 测活 → 组装 → 发布
#
#   sh run.sh                 # 全流程（无 token 则只到组装）
#   sh run.sh --limit 20      # 只测前 20 个 js 源，快速验证
#   CF_API_TOKEN=xxx CF_ACCOUNT_ID=yyy sh run.sh    # 含发布
set -e
cd "$(dirname "$0")"

LIMIT=""
if [ "$1" = "--limit" ]; then LIMIT="--limit $2"; fi

echo "=== 1/4 采集配置源"
python3 build.py --sites-only

echo
echo "=== 2/4 测活 js 源"
mkdir -p drpy/out
JS_CACHE="$PWD/drpy/jscache" OUT_DIR="$PWD/drpy/out" \
  node drpy/probe.mjs dist/sites_js.json $LIMIT

echo
echo "=== 3/4 组装订阅"
python3 make_sub.py

echo
echo "=== 4/4 发布"
if [ -n "$CF_API_TOKEN" ] && [ -n "$CF_ACCOUNT_ID" ]; then
  python3 publish.py --project fongmi --dir dist2
else
  echo "未设 CF_API_TOKEN / CF_ACCOUNT_ID，跳过发布。"
  echo "产物在 dist2/，可自行上传到任意静态托管。"
fi
