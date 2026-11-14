#!/bin/bash
# 08 部署到 Cloudflare Pages
source "$(dirname "$0")/_common.sh"
if [ "${STEP08_DEPLOY:-0}" != "1" ]; then
  echo "STEP08_DEPLOY!=1，跳过部署（未发布）"
  counters '{"deployed": false}'
  exit 10
fi
bash scripts/deploy_pages.sh || exit 20
counters '{"deployed": true}'
exit 0
