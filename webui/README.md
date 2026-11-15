# webui —— FongMi 管理台

订阅构建流水线的 Web 编排器（不重写算法，只调度 `pipeline/run_step.py`）。
这里是 `/app/working/fongmi-admin` 的源码快照，运行目录仍在本机那份。

- 启动：`bin/admin.sh start|stop|status`（默认监听 `0.0.0.0:8123`，电视可访问；只想本机用设 `ADMIN_HOST=127.0.0.1`）
- 本机订阅：`http://<本机IP>:8123/fongmi.json`；聚合接口 `/movie`、`/adult` 也由管理台提供，不需要 Cloudflare
- 依赖：`/app/working/fongmi-web/.venv`（fastapi + uvicorn）
- 页面：仪表盘 / 源 / 分类 / 运行 / 产物 / 历史
- 运行态 `run/`、`logs/`、`data/` 不入库（见 `.gitignore`）
