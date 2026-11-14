#!/bin/sh
# fongmi-admin 只读健康检查：本机端口 + API + 数据面
PORT=${ADMIN_PORT:-8123}
U="http://127.0.0.1:$PORT"
fail=0

code=$(curl -s -o /dev/null -w '%{http_code}' -m 4 "$U/api/health" 2>/dev/null)
[ "$code" = "200" ] && echo "OK   health $code" || { echo "BAD  health ${code:-000}"; fail=1; }

code=$(curl -s -o /dev/null -w '%{http_code}' -m 6 "$U/" 2>/dev/null)
[ "$code" = "200" ] && echo "OK   index $code" || { echo "BAD  index ${code:-000}"; fail=1; }

d=$(curl -s -m 8 "$U/api/dashboard" 2>/dev/null)
echo "$d" | grep -q '"clean"' && echo "OK   dashboard 可读" || { echo "BAD  dashboard 无数据"; fail=1; }

n=$(echo "$d" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["artifacts"]["clean"])' 2>/dev/null)
echo "INFO clean 站数 ${n:-?}"

if [ -f /app/working/fongmi-admin/run/admin.pid ]; then
  _p=$(cat /app/working/fongmi-admin/run/admin.pid)
  kill -0 "$_p" 2>/dev/null && echo "OK   pid $_p 存活" || { echo "BAD  pid 文件指向已死进程"; fail=1; }
else
  echo "BAD  缺 pid 文件"; fail=1
fi

[ $fail -eq 0 ] && echo "VERDICT OK" || echo "VERDICT HEAL_NEEDED"
exit $fail
