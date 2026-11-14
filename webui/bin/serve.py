#!/usr/bin/env python3
"""fongmi-admin 启动入口：自己写 pid 文件，避免用 pgrep 猜进程（会误匹配命令行）"""
import os, sys, uvicorn

HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOME)   # 用绝对路径起脚本时 cwd 不在 sys.path
PIDF = os.path.join(HOME, 'run', 'admin.pid')
PORT = int(os.environ.get('ADMIN_PORT', '8123'))

os.makedirs(os.path.dirname(PIDF), exist_ok=True)
with open(PIDF, 'w') as fh:
    fh.write(str(os.getpid()))

try:
    uvicorn.run('app.main:app', host='127.0.0.1', port=PORT, log_level='info')
finally:
    try:
        if open(PIDF).read().strip() == str(os.getpid()):
            os.unlink(PIDF)
    except Exception:
        pass
