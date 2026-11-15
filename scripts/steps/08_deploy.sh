#!/bin/bash
# 08 部署到 Cloudflare Pages
source "$(dirname "$0")/_common.sh"
if [ "${STEP08_DEPLOY:-0}" != "1" ]; then
  echo "STEP08_DEPLOY!=1，跳过部署（未发布）"
  counters '{"deployed": false}'
  exit 10
fi
if [ -x /app/working/tools/node_modules/.bin/wrangler ] || command -v wrangler >/dev/null 2>&1; then
  bash scripts/deploy_pages.sh || exit 20
else
  echo "wrangler 不可用，改用 Python Direct Upload（需 CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID）"
  cp config/artifacts.json dist2/artifacts.json
  "$PY" deploy/deploy_pages.py || exit 20
fi
counters '{"deployed": true}'
exit 0
