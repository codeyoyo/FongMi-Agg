#!/bin/bash
# deploy_pages.sh —— 部署到 Cloudflare Pages（含 _worker.js 参数路由）
#
#   sh deploy_pages.sh
#
# 凭据：优先环境变量，否则读 /app/working/instabox-keepalive/.cf_token
set -e
cd "$(dirname "$0")/.."

export CLOUDFLARE_API_TOKEN="${CLOUDFLARE_API_TOKEN:-$(cat /app/working/instabox-keepalive/.cf_token 2>/dev/null | tr -d '\n\r ')}"
# 账号 ID 不写死在仓库里：优先环境变量，其次同目录 .cf_account（已被 .gitignore 排除）
export CLOUDFLARE_ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-$(cat .cf_account 2>/dev/null | tr -d '\n\r ')}"

[ -n "$CLOUDFLARE_API_TOKEN" ] || { echo "缺 CLOUDFLARE_API_TOKEN"; exit 2; }
[ -n "$CLOUDFLARE_ACCOUNT_ID" ] || { echo "缺 CLOUDFLARE_ACCOUNT_ID"; exit 2; }

# wrangler 装在 /app/working/tools（容器重建后可能丢失，自动重装）
WR=/app/working/tools/node_modules/.bin/wrangler
if [ ! -x "$WR" ]; then
  echo "=== 安装 wrangler"
  NPM_CONFIG_GLOBAL=false npm install wrangler --no-fund --no-audit --loglevel=error \
    --prefix /app/working/tools >/dev/null 2>&1
fi

# Pages advanced mode 要求 _worker.js 在发布根目录
cp deploy/_worker.js dist2/_worker.js
# worker 运行时要读产物定义（?m=<id> 按产物过滤分类），必须随发布一起上传
cp config/artifacts.json dist2/artifacts.json

# wrangler.toml 是 Workers 版配置，pages deploy 时会干扰，临时移开
[ -f wrangler.toml ] && mv wrangler.toml wrangler.toml.bak
trap '[ -f wrangler.toml.bak ] && mv wrangler.toml.bak wrangler.toml' EXIT

echo "=== 部署 $(date '+%F %T')"
"$WR" pages deploy dist2 --project-name fongmi-sub --branch main --commit-dirty=true

echo
echo "两个入口:"
echo "  干净版 https://fm.le138.de5.net/fongmi.json"
echo "  全量版 https://fm.le138.de5.net/fongmi.json?mode=full"
echo "  极简版 https://fm.le138.de5.net/fongmi.json?mode=basic  (仅采集站，排查用)"
echo "  （默认域 https://fongmi-sub.pages.dev 同样可用）"
