#!/bin/sh
# deploy_worker.sh —— 把订阅部署成 Cloudflare Worker（支持 ?mode= 参数）
#
#   CLOUDFLARE_API_TOKEN=xxx CLOUDFLARE_ACCOUNT_ID=yyy sh deploy_worker.sh
#
# Token 权限：Account → Workers Scripts → Edit
#            （若首次创建 Worker，还需要 Account → Workers Scripts → Edit 即可）
set -e
cd "$(dirname "$0")"

if [ -z "$CLOUDFLARE_API_TOKEN" ] || [ -z "$CLOUDFLARE_ACCOUNT_ID" ]; then
  echo "缺 CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID"
  exit 2
fi

# 校验产物
for f in dist2/clean.json dist2/full.json worker.js wrangler.toml; do
  [ -f "$f" ] || { echo "缺文件: $f"; exit 1; }
done

echo "=== 安装 wrangler（本机 npm 全局目录受限，装到本地）"
NPM_CONFIG_GLOBAL=false NODE_OPTIONS= npx --yes wrangler@latest --version >/dev/null 2>&1 || {
  NPM_CONFIG_GLOBAL=false npm install wrangler --no-fund --no-audit --loglevel=error --prefix .
}

echo "=== 部署"
NPM_CONFIG_GLOBAL=false NODE_OPTIONS= npx wrangler deploy

echo
echo "=== 部署完成后的地址"
echo "  干净版（电视）: https://fongmi-sub.<你的子域>.workers.dev/fongmi.json"
echo "  全量版（自己）: https://fongmi-sub.<你的子域>.workers.dev/fongmi.json?mode=full"
