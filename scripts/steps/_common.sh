#!/bin/bash
# 步骤脚本公共头：切到仓库根、约定 counters 输出格式
set -o pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 30
REPO="$(pwd)"
counters() {  # counters '{"k":1}'
  echo "##COUNTERS## $1"
}
PY=python3
