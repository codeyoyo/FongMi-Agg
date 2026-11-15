#!/bin/bash
# 步骤脚本公共头：切到仓库根、约定 counters 输出格式
set -o pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 30
REPO="$(pwd)"
counters() {  # counters '{"k":1}'
  echo "##COUNTERS## $1"
}
PY="${FONGMI_PY:-python3}"
# Windows 原生 Python 不认识 Git Bash 的 /tmp，统一用仓库内的临时目录
TMP="state/tmp"
mkdir -p "$TMP"
