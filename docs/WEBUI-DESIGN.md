# fongmi-agg Web GUI 设计方案（提案，未实施）

> 目标：给自己用的单用户管理台。可在浏览器里增删点播/直播源、编辑分类、一键跑完
> `采集站 → 测活 → 内容分类 → 分组聚合 → 生成订阅 → 部署 Cloudflare Pages`，并能看进度、看结果、回滚。
>
> 状态：**设计稿，等拍板后再动工。** 本文只描述方案，不含已落地的代码。

---

## 0. 一句话架构

**GUI = 现有流水线的「编排器 + 配置编辑器 + 状态查看器」，不重写任何算法。**

真相（source of truth）仍然是三样东西，GUI 只是它们的友好界面：

| 真相 | 位置 | GUI 的动作 |
|---|---|---|
| 源清单 | `config/manual_sources.json`（vod / live / intl）、`config/intl_channels.json` | 读写，保存后自动 git commit |
| 算法与产物 | `builders/*.py`、`pipeline/*.py`、`dist2/*.json` | 只调用、只读概要，不复制逻辑 |
| 运行记录 | `state/runs/<run_id>/`、`logs/` | 新建、轮询、展示 |

**为什么不重写算法**：2026-11-14 一天内就踩了三个只在脚本里体现的坑——验证器读 200KB 截断、
被 URL 里的 BOM 卡死、代理 1 秒掉线被判死源。重写等于把这些坑重踩一遍。

---

## 1. 分层

```
浏览器（零构建 SPA：HTML + vanilla JS，无 npm、无 vite）
   │  HTTP + SSE
   ▼
FastAPI  fongmi-admin  (127.0.0.1:8123)
   ├─ /api/dashboard   线上版本、各产物站数、分类分布、上次运行、健康灯
   ├─ /api/sources     三个 kind 的增删改查 + dry-parse 预览
   ├─ /api/categories  分类桶与关键词 + 两两交集校验
   ├─ /api/runs        建任务 / 查进度 / 拉日志（SSE）
   ├─ /api/artifacts   读 dist2/*.json 概要、下载、发布
   └─ /api/publish     调 deploy_pages.sh（需二次确认）
   │  subprocess（串行，单工人）
   ▼
scripts/steps/01..08  ← 把 daily_update.sh 拆成可独立调用的 8 步
   ▼
dist2/*.json → Cloudflare Pages（fm.le138.de5.net）
```

---

## 2. 硬骨头：把 `daily_update.sh` 拆成 8 个 step

现在它是单体脚本：`set -e` + `exec > >(tee -a "$LOG")` + 全流程串在一个文件里。
GUI 无法「只跑测活」「只生成」「看第 3 步进度」。所以第一步改造是拆解，**且保持向后兼容**。

### 2.1 新目录

```
scripts/steps/
  01_fetch.sh      拉 zy.json + load_manual + 合并 → /tmp/zy_sites.json
  02_probe.sh      测活 → state/ok_api.json
  03_dedupe.py     去重 → state/ok_api_final.json
  04_classify.py   内容分类 → state/sites_clean.json
  05_verify.py     三层验证 → state/verify_result.json + 池合并
  06_search.py     搜索测速 → state/search_timing.json
  07_build.sh      build_modes / judge+build_groups / build_agg+build_two / build_multi
  08_deploy.sh     deploy_pages.sh
```

### 2.2 统一执行器 `pipeline/run_step.py`

```bash
python3 pipeline/run_step.py --run-id 20261114-0420-a1 --step 02_probe
```

职责：
- 起一个子进程跑对应 step，**stdout/stderr 同时写** `state/runs/<run_id>/<step>.log`
- 结束写 `state/runs/<run_id>/<step>.json`：`{step, rc, started, finished, duration_ms, counters, error}`
- 退出码语义化，GUI 按码决定「可重试 / 硬失败」：
  `0 成功` / `10 无变化` / `20 网络类失败（可重试）` / `30 硬失败`

`daily_update.sh` 退化成薄壳：`for s in 01..08; do run_step.py --step $s; done`
→ cron 用法一个字都不用改，GUI 也复用同一批 step，**不存在两套流程**。

### 2.3 关键计数（GUI 要靠它展示真实进展，而不是假进度条）

每步结束写计数，例如：

| step | counters |
|---|---|
| 01 | `sites=227, manual_added=83, live_lines=12350` |
| 02 | `tested=202, ok=98, dead=104, elapsed_s=17` |
| 04 | `clean=33, adult=20, unknown=3` |
| 05 | `full_pass=29, partial=3, dead=1` |
| 07 | `clean=198, full=220, basic=44, multi=20` |
| 08 | `files_uploaded=8, url=https://fm.le138.de5.net` |

---

## 3. 数据模型（SQLite，落 `data/admin.db`）

只存**元数据**，产物不进库（`dist/` `dist2/` 本就 gitignore）。

```sql
sources(id, kind, name, url, grp, enabled, note, added_at,
        last_probe_at, last_status, last_sites)
        -- kind ∈ vod|live|intl；grp 用于自定义分组标签

categories(id, name, order_no, rules_json, enabled)
        -- rules_json: {keywords:[], by_type:[], xkws:[]}
        -- 五分类（电影/电视剧/综艺/动漫/其它）只是初始 5 行

runs(id, kind, started_at, finished_at, status,
     steps_json, summary_json, published)
        -- status ∈ running|ok|partial|failed|canceled

snapshots(id, run_id, file, sites, total, sha256, created_at)
        -- 每次 07 之后落一份，回滚的依据

events(id, run_id, ts, level, step, message)
        -- 日志索引，支持按 step 过滤与「只看错误」
```

**来源仍以 JSON 文件为准**：`sources` 表是 `manual_sources.json` 的镜像，写库后立刻回写 JSON 并
`git commit -m "ui: +N sources"`。这样任何一次改动都能 `git diff` / `git revert`，不会变成
「只有数据库里有」的黑箱。

---

## 4. 页面（5 个，够用就行）

### 4.1 仪表盘 `/`
- 线上探活：`fm.le138.de5.net/{fongmi,clean,full,multi}.json` 的 200 + 站数 + 大小 + 生成时间
- 卡片：clean 198 / full 220 / basic 44 / multi 20 / 直播 26 组 483 频道
- 五分类分布条形（各 18 源）
- 上次运行：结果、耗时、哪个 step 用时最长
- 三盏灯：`本机服务 / 线上域名 / CF 部署凭据有效`

### 4.2 源管理 `/sources`
三个 tab（点播 / 直播 / 境外），表格列：名称、URL（截断悬浮展开）、类型、上次测活、状态、启用开关。

**批量导入是最重要的交互**：粘贴多行地址 → 点「预检」→ 后端跑
`load_manual.parse_config`（带 BOM/注释容错）→ 回显：

```
识别到 12 条：8 个单仓配置、3 个多仓（展开后 47 个子配置）、1 条解析失败（HTTP 503）
其中命中已知成人判定的 0 条
[ 取消 ]  [ 写入这 12 条 ]
```

预检不落盘、不改产物 —— 避免「粘错一串把订阅弄坏」。

### 4.3 分类 `/categories`
桶列表可拖排序；每桶可编辑 `keywords` / `by_type` / `xkws`。
**保存前强制跑一次两两交集校验**（本项目历史 bug 就是分类串味），交集非 0 时红字拦住：
`电影 ∩ 电视剧 = 3 个源，请先修正`。

### 4.4 运行 `/run`
- 勾选要跑的 step（默认全选 = 一键全流程）
- 开关：`沿用上次测活结果（省 5 分钟）`、`跑完直接发布`、`并发数（默认 12/16）`
- 右侧实时日志（SSE，按 step 分色），下方每步耗时条
- 结束给**变更摘要**，不是「成功」两个字：

```
站点 195 → 198 (+3)   multi 17 → 20 (+2)   直播 483 → 483
新增源：分享爬虫、无尽资源、魔都资源
已发布：https://fm.le138.de5.net（203.5 KB, 04:16）
```

### 4.5 产物与历史 `/artifacts`
- 每个文件：站数、大小、sha256 前 8 位、前 20 站预览、下载
- 「发布」按钮需输入 `publish` 五个字母二次确认（防误点公开）
- 历史 run 列表 → 选一条 → `回滚`：还原该 run 的 config 快照 + 重跑 07（不重跑测活，快）

---

## 5. 「一键」的真实语义（必须写在 UI 上）

8 步串行，实测耗时（本机 2 核）：

| 阶段 | 耗时 | 备注 |
|---|---|---|
| 01 拉源 | **1–4 min** | 外部配置多、海外出口慢，变量最大 |
| 02 测活 | 1–3 min | 202 站并发 16 |
| 03/04 去重+分类 | ~1 min | 分类要抽样取标题 |
| 05 三层验证 | 2–5 min | 每站 3 次请求 + 重试 |
| 06 搜索测速 | ~1 min | |
| 07 生成 | <10 s | |
| 08 部署 | ~30 s | |

**合计 8–15 分钟**。所以：

1. 进度必须按 step 展示真实状态（排队 / 运行 / 完成 / 跳过 / 失败），不做假进度条；
2. 提供「沿用上次测活结果」开关（跳过 02/05，降到 2–4 分钟）；
3. 跑完显式标注：**「本机为海外出口，测活的『死』可能是假阴性，不代表你电视端不能用」** —— 这是
   这个项目最容易被误解的一点，UI 里必须显眼。

---

## 6. 边界（一条硬约束，写进代码）

**源录入不做 18+ 通道。** 新导入的源在进池前一律过 `pipeline/classify_sites.py` 判定，
判为成人的**不进入任何订阅产物**（clean / full / basic / two / multi 都不进）。

这条与「adult.json 现状不动」并不矛盾：现有那份 25 站是历史遗留，按既有约定保留、不扩不维护；
而通过 GUI 新引入的源，不提供绕过的入口。判定逻辑复用现有分类器，不做第二套。

---

## 7. 技术选型与理由（都是被这台机器逼的）

| 选择 | 理由 |
|---|---|
| 前端**零构建**（原生 JS，无 npm/vite） | 本机 vite build 曾 OOM 被 kill（4 GB cgroup），能省就省 |
| 后端 FastAPI | `fongmi-web/.venv` 里 fastapi 0.143.1 / uvicorn 0.54.0 **已装好**，不新增依赖 |
| SQLite | 单用户、几百行数据，够用；不用 Redis/队列 |
| 串行单工人 subprocess | 2 核 3.76 GB，并发跑两条流水线必然互相拖死 |
| SSE 而非 WebSocket | 单向推日志，够用，且少一类反代坑 |
| 不套前置 Basic Auth | 应用自带单用户登录页；本环境已定「认证只留一道门」 |

---

## 8. 落点与运维（按容器重建铁律）

```
/app/working/fongmi-admin/          ← NFS 持久层，容器重建不丢
  app/                FastAPI 代码（main.py, api/*.py, static/）
  data/admin.db       SQLite（指向挂载层）
  run/admin.pid
  logs/admin.log
  bin/admin.sh        start|stop|restart|status（pid 文件停起，禁 pkill -f）
  bin/health.sh       只读探活：本地 200 + 无凭据 401 + 公网 200
  bin/heal.sh         自愈：进程 → 端口 → 公网，逐项日志
```

- 监听 `127.0.0.1:8123`（只回环）
- cloudflared 新增 ingress：`fe.le138.cc.cd → http://localhost:8123`（先备 config.yml，改完真 kill 重启）
- 操作 `fongmi-agg` 仓库时**只写 config/ 与读出 dist2/**，其余文件不动

---

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| GUI 能触发公网发布 → 误点即上线 | 发布需输入确认词；发布前自动 snapshot；可一键回滚重生成 |
| 测活假阴性被当成「源坏了」 | 结果页并排显示「本机判定」与「上次判定」，提示海外出口因素；提供跳过测活 |
| 长任务跑到一半页面关掉 | run 在后端进程里继续；重进 `/run` 按 run_id 续看日志 |
| 两套真相（库 vs git） | 写库=回写 JSON=自动 git commit；启动时以文件为准校正库 |
| 本机被重建后 venv 丢 | heal.sh 检测依赖缺失并提示；复用 fongmi-web venv 作兜底 |

---

## 10. 分期（每期都能单独用）

| 期 | 内容 | 预估 |
|---|---|---|
| **P0** | 仪表盘（只读）+ 源列表（只读）+ 一键全流程 + SSE 日志 + 产物概要 | 半天 |
| **P1** | 源增删改 + 批量导入预检 + 启用开关 | 半天 |
| **P2** | 分类编辑 + 两两交集校验 + snapshot 回滚 | 半天 |
| **P3** | 定时调度（错开网络高峰）+ 完成通知 | 2 小时 |

P0 就能替代「让你天天来问我跑一次」这件事——这才是这个 GUI 的真正价值。

---

## 11. 待拍板（三项，回答即可动工）

1. **域名**：新开 `fe.le138.cc.cd`？还是塞进现有 `fm.le138.cc.cd/admin`？
2. **暴露范围**：应用自带单用户登录后上公网，还是只在内网/本机用（不上隧道）？
3. **范围**：先做 P0（半天，能跑能看），还是 P0+P1 一起（一天，能编辑源）？
