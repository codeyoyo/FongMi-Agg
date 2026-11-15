#!/usr/bin/env python3
"""fongmi-admin 启动入口：自己写 pid 文件，避免用 pgrep 猜进程（会误匹配命令行）"""
import os, sys, uvicorn
from pathlib import Path

HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOME)   # 用绝对路径起脚本时 cwd 不在 sys.path
PIDF = os.path.join(HOME, 'run', 'admin.pid')
PORT = int(os.environ.get('ADMIN_PORT', '8123'))
# 默认监听所有网卡：FongMi 在电视/手机上也要能拉到本机订阅。
# 后台 / 与 /api/* 对非本机请求仍要登录；订阅/聚合路径是公开的。
# 只想本机用就设 ADMIN_HOST=127.0.0.1。
HOST = os.environ.get('ADMIN_HOST', '0.0.0.0')

os.makedirs(os.path.dirname(PIDF), exist_ok=True)
Path(PIDF).write_text(str(os.getpid()), encoding='utf-8')

try:
    uvicorn.run('app.main:app', host=HOST, port=PORT, log_level='info')
finally:
    try:
        if Path(PIDF).read_text(encoding='utf-8').strip() == str(os.getpid()):
            Path(PIDF).unlink(missing_ok=True)
    except Exception:
        pass
