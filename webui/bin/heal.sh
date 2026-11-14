#!/bin/sh
# fongmi-admin 自愈：本机服务不在就拉起，再验公网入口；不盲目重建
HOME_DIR=/app/working/fongmi-admin
PORT=${ADMIN_PORT:-8123}
B=$(printf 'admin:%s' "$(cat $HOME_DIR/run/.password 2>/dev/null)" | base64 | tr -d '\n')

echo "== 1) 本机端口"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 4 "http://127.0.0.1:$PORT/api/health" 2>/dev/null)
if [ "$code" != "200" ]; then
  echo "   本机 ${code:-000} → 启动"
  sh "$HOME_DIR/bin/admin.sh" start
  sleep 2
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 4 "http://127.0.0.1:$PORT/api/health" 2>/dev/null)
fi
echo "   本机 = ${code:-000}"

echo "== 2) 公网入口 https://fe.le138.cc.cd/"
unauth=$(curl -s -o /dev/null -w '%{http_code}' -m 15 --noproxy '*' https://fe.le138.cc.cd/ 2>/dev/null)
auth=$(curl -s -o /dev/null -w '%{http_code}' -m 15 --noproxy '*' -H "Authorization: Basic $B" https://fe.le138.cc.cd/ 2>/dev/null)
echo "   无凭据=$unauth（期望 401）  带凭据=$auth（期望 200）"

if [ "$code" = "200" ] && [ "$auth" = "200" ]; then
  echo "VERDICT OK"
  exit 0
fi

echo "== 3) 公网不通则查隧道"
sh /app/working/cloudflared/health.sh 2>/dev/null | tail -3
[ "$unauth" = "401" ] && [ "$auth" != "200" ] && echo "提示：401 正常但带凭据失败 → 查 run/.password 是否被重置"
echo "VERDICT HEAL_NEEDED"
exit 1
