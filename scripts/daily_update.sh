#!/bin/bash
# daily_update.sh —— 每日全流程：拉源 → 测活 → 分类 → 生成 → 部署
#
#   sh scripts/daily_update.sh            # 跑完整流程
#   sh scripts/daily_update.sh --no-deploy # 只生成不部署（本地检查）
#
# 依赖：python3、node（可选，用于本地校验 Worker）
# 部署需要：CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID
set -e
cd "$(dirname "$0")/.."
LOG="logs/daily-$(date +%Y%m%d-%H%M).log"
mkdir -p logs backup
exec > >(tee -a "$LOG") 2>&1

echo "===== $(date '+%F %T') 开始 ====="

# 1) 拉最新采集站列表（含统一入口 manual_sources.json）
echo "--- [1/8] 拉采集站列表"
curl -sS -L -m 40 -o /tmp/zy.json \
  "https://raw.githubusercontent.com/hd9211/Tvbox1/main/zy.json" \
  || { echo "拉取失败，沿用上次列表"; [ -f /tmp/zy.json ] || exit 1; }
echo "  统一入口加载："
python3 -u pipeline/load_manual.py 2>&1 | grep -E "去重后|失败" | head -2
python3 -c "
import json
d=json.load(open('/tmp/zy.json'))
s=[x for x in (d.get('sites') or d) if x.get('type') in (0,1) and str(x.get('api','')).startswith('http')]
try:
    m=json.load(open('state/manual_vod_sites.json'))
except Exception:
    m=[]
have={x['api'].rstrip('/') for x in s}
add=[x for x in m if x['api'].rstrip('/') not in have]
s += [{'name':x['name'],'api':x['api'],'type':x['type']} for x in add]
json.dump(s,open('/tmp/zy_sites.json','w'),ensure_ascii=False)
print(f'  采集站 {len(s)} 个（manual 新增 {len(add)}）')
"

# 2) 测活
echo "--- [2/8] 测活（并发 16）"
python3 pipeline/probe_api.py /tmp/zy_sites.json

# 3) 去重
echo "--- [3/8] 去重"
python3 - <<'PY'
import json, urllib.parse
from collections import defaultdict
ok = json.load(open('state/ok_api.json'))
byhost = defaultdict(list)
for s in ok:
    byhost[urllib.parse.urlparse(s['api']).netloc.lower()].append(s)
best = []
for h, lst in byhost.items():
    # 同域名下优先 type1(JSON)：解析快、字段全；同 total 时也优先 JSON
    lst.sort(key=lambda x: (x.get('_total', 0), 1 if x.get('type') == 1 else 0), reverse=True)
    best.append(lst[0])
best.sort(key=lambda x: -x.get('_total', 0))
best.sort(key=lambda x: (-x.get('_total', 0), 0 if x.get('type') == 1 else 1))
seen, uniq = set(), []
for x in best:
    t = x.get('_total', 0)
    if t and t in seen:
        continue
    if t:
        seen.add(t)
    uniq.append(x)
json.dump(uniq, open('state/ok_api_final.json', 'w'), ensure_ascii=False, indent=1)
print(f'  独立源 {len(uniq)} 个，合计 {sum(x.get("_total",0) for x in uniq):,} 部')
PY

# 4) 分类（正经 / 成人）
echo "--- [4/8] 内容分类"
python3 pipeline/classify_sites.py state/ok_api_final.json

# 5) 三层深度验证（clean 版据此收紧）
echo "--- [5/8] 三层验证（分类/列表/详情）"
python3 pipeline/verify_clean.py state/sites_clean.json

# 6) 搜索能力测速（决定站点排序与 searchable）
echo "--- [6/8] 搜索测速"
python3 pipeline/probe_search_time.py | head -6

# 7) 生成 clean.json / full.json
echo "--- [7/8] 生成 clean.json / full.json"
python3 builders/build_modes.py

# 7b) 生成两组：adult.json（成人资源组）/ other.json（其它组）
#     判定依据是站点自身的分类名（judge.py），不是站名猜测
echo "--- [7b] 生成 adult.json / other.json"
python3 pipeline/judge.py >/dev/null 2>&1 && python3 builders/build_groups.py \
  || echo "  !! 分组生成失败，沿用上一版 adult/other"

# 7ba) 国际组测活：iptv-org 的 us/jp/kr/sg 源属短时可用，实测一轮能掉一半，
#      不每天重测就会在清单里堆死频道
echo "--- [7ba] 国际组测活"
python3 live/probe_intl.py 2>&1 | tail -3 || echo "  !! 国际组测活失败，沿用上一版"

# 7bb) 播放实测：每源抽 4 部片走「详情 → 首集地址 → 校验 #EXTM3U」
#      产出 play_probe.json，是 7c 优选的门槛依据；失败则沿用上一版
echo "--- [7bb] 播放实测（优选依据）"
python3 builders/play_probe.py >/dev/null 2>&1 \
  || echo "  !! 播放实测失败，沿用上一版 play_probe.json"

# 7c) 两组聚合站点：服务端把同一组的几十个源合成一个 type:1 站点
#     two.json 的 sites 只有两条（影视资源 / 成人资源），配置本体 200KB 级
echo "--- [7c] 生成聚合站点 two.json + agg_srcs.json"
python3 builders/build_agg.py && python3 builders/build_two.py \
  || echo "  !! 聚合站点生成失败，沿用上一版"

# 7d) 多仓订阅：把统一入口里的外部配置收成一条 multi.json，
#     FongMi 加这一条就能在配置列表里切换全部外部源（jar 站点由客户端自己跑）
echo "--- [7d] 生成多仓 multi.json"
python3 builders/build_multi.py 2>&1 | tail -2 \
  && cp dist/multi.json dist2/multi.json \
  || echo "  !! 多仓生成失败，沿用上一版"

# 6) 部署
if [ "$1" = "--no-deploy" ]; then
  echo "--- [8/8] 跳过部署（--no-deploy）"
else
  echo "--- [8/8] 部署到 Cloudflare Pages"
  bash scripts/deploy_pages.sh
fi

# 保留最近 14 天日志
find logs -name 'daily-*.log' -mtime +14 -delete 2>/dev/null || true

echo "===== $(date '+%F %T') 完成，日志 $LOG ====="
