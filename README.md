# FongMi 订阅聚合

从公开仓库收集 TVBox/FongMi 采集站 → 测活 → 内容分类 → 分组聚合 → 生成订阅 → 部署到 Cloudflare Pages。

## 目录结构

```
.
├── scripts/      入口脚本（所有能直接跑的东西都在这）
├── pipeline/     采集链路：拉源 → 测活 → 去重 → 分类 → 三层验证
├── builders/     生成器：订阅文件、两组配置、聚合站点
├── live/         直播源聚合与线路测活
├── clbug/        tvbox.clbug.com 源线（独立实验链路，可单独跑）
├── deploy/       部署：Pages / Workers / _worker.js
├── prototype/    早期预研代码（不参与主流程）
├── docs/         说明与留档
├── dist/         中间产物：站点列表、js 源清单
├── dist2/        最终发布目录（Pages 上传的就是这个）
├── backup/       历史配置备份
└── logs/         每日运行日志，保留 14 天
```

| 目录 | 文件 | 作用 |
|---|---|---|
| `scripts/` | `daily_update.sh` | 每日全流程（8 步），生产入口 |
| | `run.sh` | js 源链路：采集 → node 测活 → 组装 → 发布 |
| | `daily_clbug.sh` | clbug 源刷新（5 步） |
| | `finalize_live.sh` | 直播实测数据齐了后重建并部署 |
| | `deploy_pages.sh` | 部署到 Cloudflare Pages（当前主用） |
| | `deploy_worker.sh` | 部署到 Cloudflare Workers（备选形态） |
| `pipeline/` | `build.py` | 拉取上游配置源，拆出采集站 / js 源 → `dist/` |
| | `probe_api.py` | 采集站测活（JSON `list` 非空 / XML `<video>` 非空） |
| | `merge_api.py` | 合并测活结果去重 |
| | `classify_sites.py` | 内容分类：站名关键词 + 首 20 条抽样命中率 |
| | `probe_classes.py` | 抓各站自己的分类表 → `classes_all.json` |
| | `judge.py` | 按**站内分类名**把站点分组 → `kinds2.json` |
| | `classify_all.py` | 批量分类（judge 的前置探索版） |
| | `verify_clean.py` | 三层验证（分类 / 列表 / 详情） |
| | `probe_search.py` / `probe_search_time.py` | 搜索可用性与耗时 |
| `builders/` | `build_modes.py` | 生成 `dist2/clean.json` + `full.json` |
| | `build_groups.py` | 生成两份分组配置（A 组 / B 组） |
| | `build_agg.py` | 生成 `dist2/agg_srcs.json`（聚合源清单 + 分类映射） |
| | `build_two.py` | 生成 `dist2/two.json`（sites 只有两条的聚合配置） |
| | `make_sub.py` | js 源订阅组装 |
| | `play_probe.py` | 逐片探播放地址可用性 → `play_probe.json` |
| `live/` | `merge_live.py` | 直播源合并去重 |
| | `build_live_config.py` | 生成 `live_groups.json`（含实测通过线路） |
| | `probe_all_routes.py` / `test_live_routes.py` | 直播线路测活 |
| `clbug/` | `fetch_clbug.py` / `probe_clbug.py` / `verify_clbug.py` | 拉源 / 测活 / 过滤验证 |
| | `probe_clbug_live.py` / `verify_clbug_live.py` | clbug 直播源列表与分片抽样 |
| `deploy/` | `_worker.js` | Pages advanced mode 入口，按 `?mode=` 路由 |
| | `worker.js` + `wrangler.toml` | Workers 版形态（备选） |
| | `deploy_pages.py` | 纯 API 直传实现（wrangler 不可用时兜底） |
| | `publish.py` | Direct Upload 发布 |
| | `test_worker.mjs` | 本地校验 Worker 路由 |

> 所有脚本都以**仓库根**为工作目录（`scripts/*.sh` 内部先 `cd` 到仓库根；`*.py` 用 `BASE = 仓库根` 定位数据文件），因此数据文件始终读写仓库根，可任意在根目录执行。

## 链接

订阅地址是自用入口，不在本文档公开。部署后形如 `https://<你的域名>/fongmi.json`，
其中 `sites` 是两条 `type: 1` 站点。

- 一条聚合影视采集站，站内分类名命中黑名单词的条目已剔除
- 另一条是个人用途的分组，不在此说明

两条的分类桶各自独立，关键词跟着 `agg_srcs.json` 走，不写死在 Worker 里。

两条都是 `type: 1`，设备端零依赖。**不是两份配置靠 URL 参数切换**——那正是之前被否掉的做法。

FongMi 的 `sites` 一条 = 一个源，App 不支持站点分组（`bean/Site.java` 无 group 字段）。所以"分组"的实现方式是把聚合搬到服务端：两条 `type:1` 站点分别指向两个聚合端点，Worker 内部把同组的几十个采集站并发拉取、去重、轮询交错成一个列表。

- 每条站点的分类：全部 / 电影 / 电视剧 / 综艺 / 动漫 / 纪录片 / 其它
- 分类按每部影片自带的 `type_name` 归类（多数采集站没有分类表接口，`ac=list` 直接吐列表，`t=` 参数不可信）
- 列表是各源轮询交错，避免被片库最大的那个站整页淹没
- 详情/播放地址原样透传，`s<N>|` 前缀只用于还原源
- 调试：`/other?ac=videolist&t=全部&pg=1&debug=1` 返回每个源的条数与耗时
- 网页预览：`https://<你的域名>/preview?g=other`（浏览器直接打开会有 302 跳转）

**旧链接（保留兼容）**

`?mode=full`（全量：采集站 + js 源，旧口径）、`?mode=basic`（极简）以及各分组的 `?mode=` 入口仍可用。

分组判据是**站点自身的分类名**（`pipeline/judge.py`，正规分类白名单命中 ≥8），不是猜站名：有些站名字看起来很正经，实际分类全是黑名单词，会被正确分到对应组。

## 日常命令

```bash
cd /app/working/fongmi-agg

# 完整流程（拉源 → 测活 → 分类 → 生成 → 部署）
bash scripts/daily_update.sh

# 只生成不部署（本地看结果）
bash scripts/daily_update.sh --no-deploy

# 单步
python3 pipeline/probe_api.py <站点列表.json>       # 测活 → ok_api.json
python3 pipeline/classify_sites.py ok_api_final.json # 分类 → sites_clean.json
python3 builders/build_agg.py                        # 探测各源分类约定 → dist2/agg_srcs.json
python3 builders/build_two.py                        # 生成 → dist2/two.json（两条站点）
python3 builders/build_modes.py                      # 生成 → dist2/clean.json + full.json
bash scripts/deploy_pages.sh                         # 部署

# clbug 源刷新
bash scripts/daily_clbug.sh
```

> `daily_update.sh` 用 bash 语法（`exec > >(tee ...)`），**必须用 `bash` 跑，不能用 `sh`**（本机 `sh` 是 dash）。其余脚本 sh/bash 均可。

## 聚合与优选是怎么做的

不是把 N 个源简单拼起来，四件事都在做：

1. **按站内分类拉取**（每桶最多 18 个源）。`builders/build_agg.py` 在构建期逐源探测「这个站认不认分类参数 `t=`」，
   把结果写成 `q` 模板存进 `agg_srcs.json`。运行时直接按记好的形态发请求，零试错。
   实测 18 个源里只有 3–4 个认 `t=`，其余只能拉全量再本地按 `type_name` 过滤。
2. **交错去重**。各源列表按轮询交错（`interleave`），避免被片库最大的站整页淹没；
   同名按 `vod_name` 去重。
3. **播放实测优选**（不只是"能拉到列表"）。
   `builders/play_probe.py` 对每个源抽 4 部片，走"详情 → 取首集地址 → 拉前 2KB 看是否为 `#EXTM3U`"，
   得出每源的可播率。`build_agg` 只让**可播率 ≥ 0.5** 的源进组——实测 67 个源里
   17 个完全不能播、4 个只有 1/4 能播，这两批占了两成，放进订阅就是让用户挨个踩空。
   详情页同样全线路探活：实测《折月亮》聚合出 11 条线路里有 3 条是死链，
   现在死链不返回，用户看到的每条都能真播。
4. **详情多线路**。`handleDetail` 拿全组所有源搜同名影片，命中后取各自 `vod_play_url`，
   用 `$$$` 拼成一排线路——一条挂了还能换。实测《谷雨》能并到 11 条线路。
   （这里踩过坑：早期只抽前 4 个源，恰好那 4 个商店全都不支持搜索，15 条线路缩成 1 条。）
5. **内容过滤**。除站名关键词与内容抽样外，`build_agg` 还会剔掉站内分类名命中
   黑名单词的分支——有些站的分类名叫得很直白，不剔会混进影视组。

## 为什么要做过滤

公开采集站里内容混杂的比例不低，设备给家里人共用时需要一层过滤。

判据是双层的，只看名字不够（有些站名字完全正经，实测内容命中率却有 60%）：

1. 站名关键词（快，但漏得多）
2. **内容抽样**：拉首个分类前 20 条标题，统计黑名单词命中率
   - `>20%` → 排除
   - `10–20%` → 疑似，也排除
   - 站名命中关键词且 `>5%` → 排除

抽样 20 条是启发式，可能漏网或误杀。发现不对的站，加进黑名单再跑。

## 部署形态：Pages + `_worker.js`（advanced mode）

静态托管本身无法按 URL 参数返回不同内容。`deploy/_worker.js` 放进发布根目录后，Pages 会用它接管所有请求：

```js
const target = url.searchParams.get('mode') === 'full' ? '/full.json' : '/clean.json';
return env.ASSETS.fetch(new URL(target, url.origin));
```

其余路径原样交给 `env.ASSETS`，所以 `/js/*.js`、`/lib/*.js` 这些 FongMi 按相对路径请求的规则文件也能正常返回。

```bash
bash scripts/deploy_pages.sh
```

凭据：优先环境变量 `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID`，否则读 `/app/working/instabox-keepalive/.cf_token` 与仓库根 `.cf_account`（后者已在 `.gitignore` 里）。

## 三层可用性验证

`pipeline/verify_clean.py` 对每个站点查三层，只有全通过才算真能用：

| 层 | 检查 | 说明 |
|---|---|---|
| L1 | `ac=list` 分类列表非空 | 站点活着 |
| L2 | `ac=videolist` 视频列表非空 | 有内容（依次试 `t=分类` / 不带 t / `ac=detail` 三种形态） |
| L3 | `ac=videolist&ids=` 详情拿得到 | 能进到播放页 |

之前踩过的坑：**只测到 L2 会误判**。同一个站常同时提供 JSON 和 XML 两个入口，XML 那个可能列表接口是坏的，但片库数报得更大 —— 按片库量去重就会保留坏的那个。所以去重规则是 **type1(JSON) 绝对优先**，不管片库数。

## 对接 FongMi 的真实协议

参数取自 `FongMi/TV` 的 `app/src/main/java/com/fongmi/android/tv/api/SiteApi.java`，
自测时**必须**照这四种形态发，否则测的就不是 App 会走的路：

| 场景 | 请求 | 期望 |
| --- | --- | --- |
| 首页/分类表 | `GET /movie`（无任何参数） | `{"class":[...]}` |
| 分类列表 | `GET /movie?ac=detail&t=电影&pg=1` | `{"list":[...]}` |
| 详情 | `GET /movie?ac=detail&ids=s1\|149716` | `{"list":[{…vod_play_url}]}` |
| 搜索 | `GET /movie?wd=斗罗&quick=true&extend=` | `{"list":[...]}` |

容易写错的两点：type=1 站点的分类请求 `ac` 就是 `detail`（`ac()` 只在 type=0 时返回 `videolist`），
且**没有 ids**；搜索请求**不带 ac**。曾因为按 `ac==='detail'` 判详情，把分类请求全吞成空列表。

一键回归：`python3 scripts/verify_agg.py https://<你的域名> movie`

## 已知局限

1. **js 源只是"规则能加载"**：96 个源在本机（海外出口）能 init、能拿分类，但 `category()` 拿不到列表 —— 因为国内站点正文拉不到。在用户自己网络里大概率正常，但没验证过。
2. **采集站测活结果与本地网络强相关**：本机测通 ≠ 你家网络通。反之也可能。
3. **内容分类是抽样启发式**，不是人工审核。
4. **片库数来自站点的 `total` 字段**，站点自己报的，可能虚高。
5. **详情里的线路是"探测时刻"的状态**：CF 出口与用户家里网络出口不同，探测说能播不代表用户端一定能播，反之亦然。

## 接入 tvbox.clbug.com 的源

从 `https://tvbox.clbug.com/user.php`（静态 HTML 表格，115 行）抓取全部订阅源，经「拉取 → 去重 → 测活 → 内容过滤 → 三层验证」筛出新的采集站并入配置。

```bash
bash scripts/daily_clbug.sh     # 五步全自动，约 5 分钟
```

## 留档

- `docs/sites_overview.md`：站点池概览
- `docs/legacy-classify-draft.py.txt`：早期分类草稿（语法不完整，未接入任何流程，仅留档）
