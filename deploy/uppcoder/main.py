"""Uppcoder FastAPI 入口：把仓库里的管理台 + 本机订阅服务暴露为 app。

Uppcoder 的 FastAPI 栈默认找 main.py 里的 app；这个文件可以：
  - 作为 app 根目录的 main.py（复制到仓库根），或
  - 放在 deploy/uppcoder/ 并把 app 根目录指到这里（平台支持子目录时）。
两种情况都会向上找到含 webui/ 与 pipeline/ 的仓库根。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
for _ in range(5):
    if os.path.isdir(os.path.join(ROOT, 'webui')) and os.path.isdir(os.path.join(ROOT, 'pipeline')):
        break
    parent = os.path.dirname(ROOT)
    if parent == ROOT:
        break
    ROOT = parent

sys.path.insert(0, ROOT)
os.environ.setdefault('FONGMI_REPO', ROOT)

from webui.app.main import app  # noqa: E402,F401
