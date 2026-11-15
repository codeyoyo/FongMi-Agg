# 部署到 Uppcoder（FastAPI 栈）

Uppcoder 的免费 Spark 计划：1 个应用 + 2 GB 内存 + 2 GB 磁盘 + HTTPS 地址，不需要信用卡。
本目录是部署包装，不改主流程。

## 一、平台上的操作

1. 注册后：**Stacks → Create → Blank stack**，添加 **FastAPI**（不需要 PostgreSQL，本项目用 JSON 文件）。
2. 连接本仓库 Git；如果有「app 根目录 / working directory」选项，填 `deploy/uppcoder`。
   - 如果平台强制以仓库根为 app 根：把本目录的 `main.py`、`requirements.txt`、`startup-app.sh`
     复制到仓库根。**这会违反仓库 AGENTS.md 的“根目录只放 4 个文件”约定**，需要你确认后例外。
3. 环境变量（Stacks → 应用设置）：
   - `ADMIN_PASS`：后台登录密码（必填，否则非本机访问后台一律 401）
   - `FONGMI_PUBLIC`：默认 `https://fm.le138.de5.net`，用于仪表盘「线上入口」探活
   - 不需要 `PORT`：平台会注入；`startup-app.sh` 会用它
4. 部署后把应用从 **Private 切到 Public**，否则 FongMi 拉不到订阅。
5. 打开应用地址，进「运行」→「一键全流程」跑一次，生成 `dist2/`（首次部署时它是空的，因为 `dist2/` 被 gitignore）。
   之后订阅地址是：

   ```
   https://<你的-app-地址>/fongmi.json
   ```

## 二、启动方式

- 默认：`python3 -m uvicorn webui.app.main:app --host 0.0.0.0 --port $PORT`
- 或平台支持自定义启动命令：`sh deploy/uppcoder/startup-app.sh`
- `startup-app.sh` 会设置 `FONGMI_REPO`、`FONGMI_PY`、`ADMIN_PORT`。

## 三、限制与注意

- **生成数据不随 Git 走**：`dist2/`、`state/`、`backup/`、`debug/` 都在 `.gitignore` 里。首次部署后必须跑一次流水线；
  之后如果平台重建容器会丢，需要重跑或自行备份（免费盘 2 GB，每晚备份）。
- **不需要 Node**：管理台、本机订阅、01–07 流水线都是 Python；只有 Cloudflare 的 `deploy_pages.sh` 用 wrangler/npm。
  在 Uppcoder 上要发 Cloudflare，可改用 `python3 deploy/deploy_pages.py` 并提供 `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID`。
- **网络**：聚合接口和测活要出网。Uppcoder 所在区域到国内源的连通性决定测活结果；建议先跑「一键全流程」看通过率。
- **后台保护**：订阅/聚合路径公开；`/` 与 `/api/*` 对非本机请求要 Basic 登录。设 `ADMIN_PASS`。
- **协议同步**：本机聚合是 `webui/app/aggregate.py`，Cloudflare 是 `deploy/_worker.js`，改协议要同步改两处。
