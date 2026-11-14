#!/bin/sh
# fongmi-admin 启停。pid 由 bin/serve.py 自己写，脚本只读不做进程猜测
HOME_DIR=/app/working/fongmi-admin
PY=/app/working/fongmi-web/.venv/bin/python
PIDF=$HOME_DIR/run/admin.pid
LOG=$HOME_DIR/logs/admin.log
PORT=${ADMIN_PORT:-8123}
export ADMIN_PORT=$PORT
mkdir -p "$HOME_DIR/logs" "$HOME_DIR/run"

alive() {
  [ -f "$PIDF" ] || return 1
  _p=$(cat "$PIDF" 2>/dev/null)
  [ -n "$_p" ] || return 1
  kill -0 "$_p" 2>/dev/null
}

case "$1" in
  start)
    if alive; then echo "already running pid $(cat "$PIDF")"; exit 0; fi
    rm -f "$PIDF"
    cd "$HOME_DIR" || exit 1
    setsid "$PY" "$HOME_DIR/bin/serve.py" >> "$LOG" 2>&1 < /dev/null &
    i=0
    while [ $i -lt 40 ]; do
      if curl -sf -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
        echo "ready after ${i}s (pid $(cat "$PIDF" 2>/dev/null))"; exit 0
      fi
      i=$((i+1)); sleep 1
    done
    echo "start TIMEOUT，看 $LOG"; tail -20 "$LOG"; exit 1
    ;;
  stop)
    if alive; then
      _p=$(cat "$PIDF")
      kill "$_p" 2>/dev/null
      i=0
      while [ $i -lt 10 ] && kill -0 "$_p" 2>/dev/null; do i=$((i+1)); sleep 1; done
      echo "stopped $_p"
    else
      echo "not running"
    fi
    rm -f "$PIDF"
    ;;
  restart)
    "$0" stop; sleep 1; "$0" start
    ;;
  status)
    if alive; then echo "up pid $(cat "$PIDF") port $PORT"; else echo "down"; fi
    ;;
  *)
    echo "用法: $0 start|stop|restart|status"; exit 1
    ;;
esac
