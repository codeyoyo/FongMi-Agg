# AGENTS.md — fongmi-agg 开发守则

面向在本仓库动手的 agent / 协作者。**动手前先读完这一页**，尤其是下面两条硬规矩。

---

## 两条硬规矩（用户 2026-11-14 明确要求）

### 1. 做任何开发前，先充分熟悉 [FongMi/TV](https://github.com/FongMi/TV)

这个项目的产出物是给 **FongMi（影視TV）客户端**吃的配置。不熟悉客户端怎么解析配置，
写出来的 JSON 字段名对、语义错，客户端不报错、只是空列表——这种错误在服务端测不出来。

**具体到动作**，不是"读过 README 就算"：

| 你要改的东西 | 必须先去核对 |
|---|---|
| `sites` 里任何字段、`type` 语义、`api` 形态 | [配置字典 · Site](https://fongmi.github.io/TV/config/) 的 19 个栏位表 |
| `lives` / group / channel / 多线路 / epg / catchup | 同页 `LiveConfig`、`Group / Channel`（20 栏位）、TXT/M3U/JSON 三种输入格式 |
| 顶层字段（`spider`/`parses`/`doh`/`headers`/`rules`/`hosts`/`ads`/`flags`…） | 同页 `VodConfig 顶层欄位`（18 个）与 `共用物件` |
| 爬虫接口、`ext`、`playerContent` 返回结构 | [爬蟲介接](https://fongmi.github.io/TV/spider/) |
| 本地 HTTP 端点（本仓库聚合服务的形态） | [本地 API](https://fongmi.github.io/TV/local/) |
| App 行为（播放、直播、搜索、站点切换） | [App 功能](https://fongmi.github.io/TV/features/) |

**禁止凭印象写字段。** 拿不准就 `web_fetch` 拉官方页面确认，或者直接读客户端源码
（`FongMi/TV` 默认分支是 **`fongmi`**，不是 `main`；`SiteApi.java` 在
`app/src/main/java/com/fongmi/android/tv/api/SiteApi.java`）。

### 2. 项目文件必须按目录划分存放

**根目录只允许出现**：`README.md`、`AGENTS.md`、`.gitignore`、`.gh_token`（凭据，已 ignore）。
除此之外**不许往根目录新增任何文件**——json 数据、临时脚本、调试输出、打包产物一律归位。

| 目录 | 放什么 | 谁写 | 进 git |
|---|---|---|---|
| `config/` | **人工维护的输入**：`manual_sources.json`、`intl_channels.json`、`sources.txt` | 人改 | ✅ |
| `state/` | **构建中间产物**：测活结果、分类结果、合并后的直播池、分组输出…全部可再生成 | 脚本写 | ❌ ignore |
| `debug/` | 一次性排障残留（`clbug_*.json` 等），确认无用的直接删 | 排障时 | ❌ ignore |
| `pipeline/` | 采集链路：拉源 → 测活 → 去重 → 分类 → 三层验证 | 开发 | ✅ |
| `builders/` | 生成器：订阅文件、两组配置、聚合站点、多仓 | 开发 | ✅ |
| `live/` | 直播源合并、线路测活、分组（含 `split_other.py`） | 开发 | ✅ |
| `scripts/` | 所有可直接执行的入口脚本 | 开发 | ✅ |
| `deploy/` | Pages / Workers / `_worker.js` | 开发 | ✅ |
| `dist/` `dist2/` | 发布产物（`dist2/` 是 Pages 上传目录） | 脚本写 | ❌ |
| `backup/` | 历史配置备份 | 脚本写 | ❌ |
| `logs/` | 每日运行日志，保留 14 天 | 脚本写 | ❌ |
| `docs/` | 说明与留档 | 人写 | ✅ |
| `prototype/` | 早期预研，**不参与主流程** | — | ✅ |
| `clbug/` | tvbox.clbug.com 独立实验链路 | — | ✅ |

**新增数据文件时的判断**：人能编辑、要长期维护 → `config/`；脚本产物、丢了能重跑出来 → `state/`。
写完记得确认 `.gitignore` 覆盖了 `state/`。

---

## 这个项目是什么

从公开仓库收集 TVBox/FongMi 采集站与直播源 → 测活 → 内容分类 → 分组聚合 → 生成订阅 JSON
→ 部署到 Cloudflare Pages。对外只有一个入口文件 `dist2/fongmi.json`（`?mode=` 切口径）。

数据流：

```
上游配置源 ──┐
manual_sources.json ──┴─→ pipeline/load_manual ─→ probe ─→ classify ─→ verify
                                                          ↓
                                                    state/ok_api_final.json
                                                          ↓
                                                  builders/*.py ─→ dist2/*.json
直播 m3u/txt ──→ live/merge_live ─→ probe_all_routes ─→ build_live_config
                                                          ↓
                                              state/live_groups.json ─→ split_other
                                                          ↓
                                                   builders/build_two.py
```

所有脚本以**仓库根**为工作目录；Python 里统一用 `BASE = 仓库根` 定位，
数据文件一律写成 `os.path.join(BASE, 'state', 'x.json')` / `os.path.join(BASE, 'config', 'x.json')`。
**不要写裸相对路径**（`open('x.json')`）——cwd 一变就断。

---

## FongMi 客端的三个结构性事实（不理解会一直撞墙）

### 1. App 不内建任何内容源

官方原话：「App 本身不內建或提供任何內容來源」。用户"找不到能看的"是产品设计，不是配置错了。
我们做的一切就是替他补这一层。

### 2. `sites` 一条 = 一个源，App 不支持站点分组

`bean/Site.java` 没有 group 字段。所以"分组"只能搬到服务端做：
两条 `type:1` 站点各自指向一个聚合端点，Worker 内部并发拉几十个采集站、去重、轮询交错成一个列表。
**不要试图用 `sites` 的字段做分组**，没有这个字段。

### 3. `type` 决定能不能在本机测活

| type | 含义 | 本机可测 |
|---|---|---|
| 0 | XML HTTP | ✅ 纯 HTTP |
| 1 | JSON HTTP | ✅ 纯 HTTP（**优先选它**，去重时 JSON 绝对优先） |
| 3 | JAR / PY / JS（Spider） | ❌ 要宿主运行时；jar 是 Android dex，`java -jar` 跑不了 |
| 4 | HTTP 扩展（分类走 Base64 ext） | ✅ 纯 HTTP |

TVBox 生态 90%+ 是 `type 3`。**跨配置合并 jar 站点不可能**——每个配置自带不同的 spider，
而 FongMi 一个配置只能挂一个 `spider`。解法是把整份配置塞进 `multi.json` 多仓，让客户端自己跑。

### 4. 直播是三层结构，多线路靠 `$标签`

```
lives[] → groups[] → channel[] → urls[]（"https://…/main.m3u8$主線"）
```

同一频道给多个 `urls` 就是多线路，`$` 后面是线路名。TXT 格式同理用 `#` 分隔多地址、
`#genre#` 分分组。改直播生成逻辑时按这个结构产出，别自造字段。

---

## 对接协议：最容易错的四处

参数取自 `SiteApi.java`，**自测必须照这四种形态发**，否则测的不是 App 会走的路：

| 场景 | 请求 | 期望 |
|---|---|---|
| 首页/分类表 | `GET <api>` 无参数 | `{"class":[...]}` |
| 分类列表 | `GET <api>?ac=detail&t=电影&pg=1` | `{"list":[...]}` |
| 详情 | `GET <api>?ac=detail&ids=s1\|149716` | `{"list":[{…vod_play_url}]}` |
| 搜索 | `GET <api>?wd=斗罗&quick=true&extend=` | `{"list":[...]}` |

1. `type=1` 站点的分类请求 `ac` 就是 `detail`（只有 `type=0` 才用 `videolist`），且**没有 ids**。
2. 搜索请求**不带 ac**。
3. 曾因为按 `ac==='detail'` 判详情，把分类请求全吞成空列表。
4. 回归命令：`python3 scripts/verify_agg.py https://<域名> movie`。

---

## 改动流程与验证

| 改了什么 | 必须跑 |
|---|---|
| `pipeline/` 采集/测活/分类 | `bash scripts/daily_update.sh --no-deploy` |
| `builders/` 生成器 | 同上，或单独 `python3 builders/build_modes.py` 后看输出站点数与字节数是否合理 |
| `live/` 直播 | `bash scripts/finalize_live.sh`（会重建 + 部署） |
| `deploy/_worker.js` 路由 | `node deploy/test_worker.mjs` + 真域名四种形态各请求一次 |
| 上线前 | `python3 scripts/verify_agg.py <域名> movie`（四形态全绿才算完） |

**只有 `dist2/` 会被部署**，改完不重新生成等于没改。

---

## 踩过的坑（重犯过一次的都在这）

1. **HTTP 200 不代表活着**：geo-block 会返回 200 + 纯文本；m3u8 必须校验 body 以 `#EXTM3U` 开头。
2. **只测 L2 会误判**：同站常有 JSON/XML 双入口，XML 那个列表接口坏但 `total` 更大 →
   按片库量去重会保留坏的。**type1 绝对优先，不看片库数**。
3. **`if good:` 会把全死频道原样保留**（`good` 为空时跳过过滤）。
4. **测活 key 对不上**：`tested` 用 canon 归一后的名字，`live_merged` 是另一种归一化，
   查表前必须过 canon。
5. **js 源曾一直读固定备份**（`backup/fongmi-pre-mode.json`），测活结果从来没生效过。
6. **`pkill -f <关键词>` 会匹配到自己**（命令行里含关键词），误杀执行 shell → 用 PID。
7. **`sh` 是 dash**：`daily_update.sh` 用了 `exec > >(tee …)` 等 bash 语法，**必须 `bash` 跑**。
8. **本机是海外出口**：国内运营商 IPTV、国内影视站正文大量连不上，
   本机测出的"死"不可信、"活"也可能只是碰巧。写结论时要标注这一点。
9. **`emptyOutDir` 类构建**（前端那些）失败会放大成白屏，产物校验不能省。
10. **容器 rebuild 会清 `/root`**，凭据只在 `/app/working` 里才活得下来。
11. **移动数据文件后必须全仓扫引用，别只扫 `scripts/`**。2026-11-14 把 `clbug_*.json` 移进
    `debug/` 时，第一轮只 grep 了 `clbug/` 和 `scripts/`，漏掉 `builders/build_modes.py`、
    `pipeline/judge.py`、`pipeline/classify_all.py`、`pipeline/probe_classes.py` 四处，
    结果 `daily_update.sh` 第 7b 步**静默失败**（`judge.py` 的 stderr 被判 `>/dev/null` 吞掉，
    只留一行「分组生成失败，沿用上一版」）。扫描命令要覆盖全部代码目录：
    ```bash
    grep -rn "要移动的文件名" --include=*.py --include=*.sh . | grep -v node_modules
    ```
    并且**改完必须真跑一次完整流水线**——单跑某个脚本通过不代表 `daily_update.sh` 里能过。

---

## 提交与部署纪律

- 远端：`git@github.com:codeyoyo/FongMi-Agg.git`（https 形态），**主分支叫 `main`**。
  本地 clone 出来可能是 `master`，直接 `git push origin master` 会**新建一条游离分支**（踩过）。
  正确：`git push origin master:main`，或先 `git branch -m master main && git branch -u origin/main`。
- 凭据在 `.gh_token`（已 ignore），推法见 `MEMORY.md` 同名条目，**不要再问用户要 PAT**。
- 提交前 `git status` 确认没有 `state/`、`debug/`、`.gh_token`、`.cf_account` 混进去。
- 生成物（`dist/`、`dist2/`、`state/`）不进 git，部署走 `scripts/deploy_pages.sh`。

---

## 加源只改一个文件

`config/manual_sources.json`，三类：

```json
{
  "vod":   [{"name": "某站", "url": "https://example.com/tvbox.json", "src": "manual"}],
  "live":  [{"name": "某直播", "url": "https://example.com/live.m3u"}],
  "intl":  [{"name": "某境外台", "url": "https://example.com/x.m3u8", "cc": "us"}]
}
```

`vod` 支持 TVBox JSON、多仓索引 `{"urls":[...]}`（递归展开一层）、TXT；只保留 `type 0/1/4`。
整份配置（含 jar 站点）走 `builders/build_multi.py` 进 `multi.json`。
