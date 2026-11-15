#!/bin/sh
# Uppcoder 自定义启动命令：从 deploy/uppcoder/ 或仓库根执行都可以。
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$HERE
if [ ! -d "$ROOT/webui" ]; then
  ROOT=$(cd "$ROOT/../.." && pwd)
fi
cd "$ROOT"

export FONGMI_REPO="$ROOT"
export FONGMI_PY="${FONGMI_PY:-python3}"
export ADMIN_PORT="${ADMIN_PORT:-${PORT:-8000}}"

exec python3 -m uvicorn webui.app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
