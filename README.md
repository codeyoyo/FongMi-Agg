# FongMi 订阅聚合

从公开仓库收集 TVBox/FongMi 采集站 → 测活 → 内容分类 → 生成两版订阅 → 部署到 Cloudflare Workers。

## 链接

**主入口（2026-11-13 起）：只有两个组**

```
https://fm.le138.de5.net/fongmi.json        → sites 里就两条：其它 / 成人资源
```

FongMi 的 `sites` 一条 = 一个源，App 不支持站点分组。所以"两组"的实现方式是把
聚合搬到服务端：两条 `type:1` 站点分别指向 `/other` 和 `/adult`，Worker 内部
把同组的几十个采集站并发拉取、去重、轮询交错成一个列表。

- 每条站点的分类：全部 / 电影 / 电视剧 / 综艺 / 动漫 / 纪录片 / 其它
- 分类按每部影片自带的 `type_name` 归类（多数采集站没有分类表接口，`ac=list`
  直接吐列表，`t=` 参数不可信）
- 列表是各源轮询交错，避免被片库最大的那个站整页淹没
- 详情/播放地址原样透传，`s<N>|` 前缀只用于还原源
- 调试：`/other?ac=videolist&t=全部&pg=1&debug=1` 返回每个源的条数与耗时

**旧链接（保留兼容）**

**两组（2026-11-13 起）**——FongMi 的 `sites` 是扁平数组，App 本身没有站点分组字段
（`bean/Site.java` 无 group），所以"两个组"落地为两份配置，在 FongMi「设置 → 配置」
里加两条，切换配置就是切组：

```
https://fm.le138.de5.net/fongmi.json?mode=other    → 其它组（42 正经采集站 + 96 js 源）
https://fm.le138.de5.net/fongmi.json?mode=adult    → 成人资源组（25 采集站）
```

分组判据是**站点自身的分类名**（`judge.py`，正规分类白名单命中 ≥8），不是猜站名：
`乐播/鲨鱼/森林/番号` 这类名字正经、实际分类全是成人词的站会被正确归到成人组。

**旧链接（保留兼容）**：

```
https://fm.le138.de5.net/fongmi.json              → 干净版（不含成人站）
https://fm.le138.de5.net/fongmi.json?mode=full    → 全量（采集站 + js 源，旧口径）
https://fongmi-sub.pages.dev/fongmi.json          → 备用域，同内容
```

站点顺序即"优选"：按片库量降序，能搜到的靠前。

## 为什么要两个版本

公开采集站里成人资源站占比很高（实测 56 个里 18 个明确成人、4 个疑似）。家里电视给别人看，需要一层过滤。

过滤判据是双层的，只看名字不够（`玉兔资源` 名字正经，实测命中率 60%）：

1. 站名关键词（快，但漏得多）
2. **内容抽样**：拉首个分类前 20 条标题，统计成人关键词命中率
   - `>20%` → 成人，排除
   - `10–20%` → 疑似，也排除
   - 站名命中关键词且 `>5%` → 成人

抽样 20 条是启发式，可能漏网或误杀。发现不对的站，加进黑名单再跑。

## 日常命令

```sh
cd /app/working/fongmi-agg

# 完整流程（拉源 → 测活 → 分类 → 生成 → 部署）
sh daily_update.sh

# 只生成不部署（本地看结果）
sh daily_update.sh --no-deploy

# 单步
python3 probe_api.py <站点列表.json>   # 测活 → ok_api.json
python3 classify_sites.py ok_api_final.json  # 分类 → sites_clean.json
python3 build_modes.py                 # 生成 → dist2/clean.json + full.json
sh deploy_worker.sh                    # 部署
```

## 文件说明

| 文件 | 作用 |
|---|---|
| `worker.js` | 入口路由，按 `?mode=` 返回对应文件 |
| `wrangler.toml` | Workers 配置，`run_worker_first` 保证参数不被静态文件吃掉 |
| `dist2/clean.json` | 干净版订阅 |
| `dist2/full.json` | 全量版订阅 |
| `dist2/js/` `dist2/lib/` | 96 个 js 源的规则文件 + drpy 引擎 |
| `probe_api.py` | 采集站测活（判据：JSON `list` 非空 / XML `<video>` 非空） |
| `classify_sites.py` | 内容分类（站名 + 抽样命中率） |
| `build_modes.py` | 生成两个版本 |
| `daily_update.sh` | 全流程编排 |
| `deploy_worker.sh` | 部署 |
| `backup/` | 历史配置 |
| `logs/` | 每日运行日志，保留 14 天 |

## 部署形态：Pages + `_worker.js`（advanced mode）

静态托管本身无法按 URL 参数返回不同内容。`deploy/_worker.js` 放进发布根目录后，Pages 会用它接管所有请求：

```js
const target = url.searchParams.get('mode') === 'full' ? '/full.json' : '/clean.json';
return env.ASSETS.fetch(new URL(target, url.origin));
```

其余路径原样交给 `env.ASSETS`，所以 `/js/*.js`、`/lib/*.js` 这些 FongMi 按相对路径请求的规则文件也能正常返回。一份 `dist2/` 同时服务两个入口。

部署命令：

```sh
bash deploy_pages.sh
```

（`wrangler.toml` 是纯 Workers 版的旧配置，`pages deploy` 前会被临时移开，避免干扰。）

## 三层可用性验证

`verify_clean.py` 对每个站点查三层，只有全通过才算真能用：

| 层 | 检查 | 说明 |
|---|---|---|
| L1 | `ac=list` 分类列表非空 | 站点活着 |
| L2 | `ac=videolist` 视频列表非空 | 有内容（依次试 `t=分类` / 不带 t / `ac=detail` 三种形态） |
| L3 | `ac=videolist&ids=` 详情拿得到 | 能进到播放页 |

之前踩过的坑：**只测到 L2 会误判**。同一个站常同时提供 JSON 和 XML 两个入口，XML 那个可能列表接口是坏的，但片库数报得更大 —— 按片库量去重就会保留坏的那个。所以去重规则是 **type1(JSON) 绝对优先**，不管片库数。

## 已知局限

1. **js 源只是"规则能加载"**：96 个源在本机（海外出口）能 init、能拿分类，但 `category()` 拿不到列表 —— 因为国内站点正文拉不到。在用户自己网络里大概率正常，但没验证过。
2. **采集站测活结果与本地网络强相关**：本机测通 ≠ 你家网络通。反之也可能。
3. **成人分类是抽样启发式**，不是人工审核。
4. **片库数来自站点的 `total` 字段**，站点自己报的，可能虚高。
5. **不含直播源**：国内运营商 IPTV 在本机 0/40 通过，代码层面无解。

## 2026-11-13 扩充：接入 tvbox.clbug.com 的 115 个源

从 `https://tvbox.clbug.com/user.php`（静态 HTML 表格，115 行）抓取全部订阅源，
经「拉取 → 去重 → 测活 → 成人过滤 → 三层验证」筛出 30 个新采集站并入配置。

| 版本 | 采集站 | 总数 | 片库 |
| --- | --- | --- | --- |
| 干净版 | 24 → **41** | 120 → **137** | 271 万 → **447 万部** |
| 全量版 | 56 → **67** | 152 → **163** | 696 万 → **804 万部** |

直播源从 3 个扩到 **10 个**，共 77,000+ 频道；三个 100% 抽样存活（虎牙 1076 / 斗鱼 923 / 肥羊YY 535）。

一键刷新源池：

```sh
sh daily_clbug.sh          # 五步全自动，约 5 分钟
sh daily_update.sh         # 每日主流程，默认会先跑上面这个
SKIP_CLBUG=1 sh daily_update.sh   # 跳过 clbug 刷新
```

新增脚本：`fetch_clbug.py`（拉源）/ `probe_clbug.py`（测活）/ `verify_clbug.py`（成人过滤+三层验证）/
`probe_clbug_live.py`（直播列表）/ `verify_clbug_live.py`（分片抽样）。
