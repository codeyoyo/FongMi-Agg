# webui —— FongMi 管理台

订阅构建流水线的 Web 编排器（不重写算法，只调度 `pipeline/run_step.py`）。
这里是 `/app/working/fongmi-admin` 的源码快照，运行目录仍在本机那份。

- 启动：`bin/admin.sh start|stop|status`（默认 `127.0.0.1:8123`）
- 依赖：`/app/working/fongmi-web/.venv`（fastapi + uvicorn）
- 页面：仪表盘 / 源 / 分类 / 运行 / 产物 / 历史
- 运行态 `run/`、`logs/`、`data/` 不入库（见 `.gitignore`）
