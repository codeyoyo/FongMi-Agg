#!/usr/bin/env python3
"""build_agg.py —— 为服务端聚合 API 预生成"源 → 分类(tid)"映射

输出 dist2/agg_srcs.json：
{
  "other": {"buckets": [{"name":"电影","srcs":[{"api":..,"type":..,"tid":"1","total":171784,"name":"暴风"}, ...]}, ...]},
  "adult": {...}
}

标准分类桶把各源五花八门的 tid 对齐，App 里只看到 6 个分类，
每个分类背后是 N 个源合并。
"""
import json, os, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(BASE, 'dist2')
UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}

# 分类桶 → 归类关键词（按顺序匹配，先命中先用）
BUCKETS = [
    ('电影', ['电影', '片']),
    ('电视剧', ['电视剧', '连续剧', '剧集', '剧']),
    ('综艺', ['综艺']),
    ('动漫', ['动漫', '动画']),
    ('纪录片', ['纪录']),
]
# 站内分类名里出现这些词的，一律不进「影视资源」组
# （实测爱蛋「福利视频」、优质资源库「福利」就是成人分类，混进去等于漏过滤）
ADULT_KWS = ('福利', '情色', '伦理', '写真', '无码', '三级', '自拍', '主播',
             '抖阴', '偷拍', '人妻', '激情', '约炮', '里番', '丝袜', '成人')

# 成人站的点播分类和影视站不是一回事：套用影视那套会把一大半内容塞进「其它」
ADULT_BUCKETS = [
    ('国产', ['国产', '自拍', '主播', '传媒', '91', '抖阴', '视频一区', '视频1区']),
    ('日本', ['日本', '日韩', '无码', '有码', '片商', '中文字幕']),
    ('欧美', ['欧美', '西方']),
    ('动漫', ['动漫', '动画', '卡通']),
    ('伦理', ['伦理', '三级', '剧情', '短剧']),
]
# 分类排除词：单字关键词会误伤——
# 「电视剧」的 kws 含「剧」，会把「喜剧片/剧情片」一起收进来；
# 「电影」的 kws 含「片」，会把「动漫电影」和动漫分类重复。
BUCKET_XKWS = {
    '电影': ['动漫'],
    '电视剧': ['片', '动漫'],
}
GROUP_BUCKETS = {'other': BUCKETS, 'adult': ADULT_BUCKETS}
GROUP_ORDER = {
    'other': ['电影', '电视剧', '综艺', '动漫', '纪录片', '其它'],
    'adult': ['国产', '日本', '欧美', '动漫', '伦理', '其它'],
}

MAX_SRC_PER_BUCKET = 18   # Cloudflare 每请求 subrequest 上限 50，留足余量


def _get(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.read(300000).decode('utf-8', 'ignore')
    except Exception:
        return None


def _parse_classes(body, typ):
    pairs = []
    if typ == 0:
        seg = re.search(r'<class>(.*?)</class>', body, re.S)
        text = seg.group(1) if seg else body
        for m in re.finditer(r'<ty\s+id="([^"]+)"\s*>([^<]*)</ty>', text):
            pairs.append((m.group(1).strip(), m.group(2).strip()))
    else:
        try:
            j = json.loads(body)
        except Exception:
            return pairs
        for c in (j.get('class') or []):
            pairs.append((str(c.get('type_id')), str(c.get('type_name') or '')))
    return pairs


CACHE_FILE = os.path.join(DIST, 'classes_cache.json')
CACHE_TTL = 7 * 86400          # 站点分类表一周内基本不变
_cache = {}


def load_cache():
    global _cache
    try:
        _cache = json.load(open(CACHE_FILE))
    except Exception:
        _cache = {}


def save_cache():
    try:
        json.dump(_cache, open(CACHE_FILE, 'w'), ensure_ascii=False)
    except Exception:
        pass


def fetch_classes(site):
    api, typ = str(site.get('api') or ''), site.get('type')
    ent = _cache.get(api)
    if ent and ent.get('c') and time.time() - ent.get('t', 0) < CACHE_TTL:
        return {**site, '_cls': [(str(a), str(b)) for a, b in ent['c']], '_via': 'cache'}
    # FongMi 取分类表走的是「无参数 GET api」（见 SiteApi.homeContent）；
    # 只有部分站才认 ac=list。两个形态都试，且各重试一次（这些站抖动很大）。
    sep = '&' if '?' in api else '?'
    for url in (api, api + sep + ('ac=list&at=xml' if typ == 0 else 'ac=list')):
        for _ in range(2):
            body = _get(url)
            if not body:
                continue
            pairs = _parse_classes(body, typ)
            if pairs:
                _cache[api] = {'t': time.time(), 'c': pairs[:80]}
                return {**site, '_cls': pairs[:80], '_via': 'bare' if url == api else 'ac=list'}
    ent = _cache.get(api)
    if ent and ent.get('c'):        # 抓不到就退回过期缓存，别让源凭空消失
        return {**site, '_cls': [(str(a), str(b)) for a, b in ent['c']], '_via': 'stale'}
    return {**site, '_cls': [], '_cerr': 'no class'}


def _count(url, typ):
    body = _get(url)
    if not body:
        return 0
    if typ == 0 or body.lstrip().startswith('<'):
        return len(re.findall(r'<video>', body))
    try:
        return len(json.loads(body).get('list') or [])
    except Exception:
        return 0


def probe_tid(site, tid):
    """返回该源对某个 tid 的可用形态：'t' 表示 t= 生效，'all' 表示只能拉全量后本地过滤"""
    api, typ = str(site.get('api') or ''), site.get('type')
    sep = '&' if '?' in api else '?'
    tail = '&at=xml' if typ == 0 else ''
    q = 'ac=videolist&t=%s&pg=1' % tid
    if _count(api + sep + q + tail, typ) > 0:
        return 't'
    return 'all'


def bucket_of(name, table=None):
    for b, kws in (table or BUCKETS):
        for k in kws:
            if k in name:
                return b
    return '其它'


def main():
    load_cache()
    kinds = json.load(open(os.path.join(BASE, 'kinds2.json')))
    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(fetch_classes, kinds))

    # 播放实测结果（play_probe.py）：只把"详情能出 + 播放地址真的是 m3u8"的源收进池子
    quality = {}
    try:
        for r in json.load(open(os.path.join(BASE, 'play_probe.json'))):
            quality[r['name']] = {'play': int(r.get('play_ok') or 0),
                                  'n': int(r.get('n') or 0),
                                  'rate': float(r.get('rate') or 0)}
        print(f'播放实测：{sum(1 for v in quality.values() if v["play"] > 0)}/{len(quality)} 源有可播样本')
    except FileNotFoundError:
        print('!! 没有 play_probe.json，本轮不做播放筛选')

    out = {}
    for grp, want in (('other', 'clean'), ('adult', 'adult')):
        srcs = [r for r in rows if r['_kind'] == want and r.get('_cls')]
        if quality:
            for r in srcs:
                r['_q'] = quality.get(r['name'], {})
            # 优选门槛：4 条样本里至少一半能真播。只要求"有 1 条能播"太松——
            # 实测有 4 个源是 1/4，等于用户点四部片三部落空
            # 注意区分「测过不合格」和「本轮没测到」：新源没数据时 rate 也是 0，
            # 若一并剔除，新源永远进不来
            measured = [r for r in srcs if r['name'] in quality]
            fresh = [r for r in srcs if r['name'] not in quality]
            good = [r for r in measured if r['_q'].get('rate', 0) >= 0.5]
            if len(good) < 6:                      # 太少了才放宽到"至少 1 个能播"
                good = [r for r in measured if r['_q'].get('play', 0) >= 1]
            if len(good) >= 3:
                srcs = good + fresh                # 未测的留着，排后面等下轮实测
            print(f'  优选后 {grp}: {len(srcs)} 源（合格 {len(good)} + 未测 {len(fresh)}）')
        srcs.sort(key=lambda x: (-x.get('_q', {}).get('rate', 0), -int(x.get('_total') or 0)))
        # 先列候选，再并发探测：串行探测 200+ 次会让这一步跑上十分钟
        cands = []
        for r in srcs:
            seen = set()
            for tid, cname in r['_cls']:
                if grp == 'other' and any(k in cname for k in ADULT_KWS):
                    continue
                b = bucket_of(cname, GROUP_BUCKETS[grp])
                if b in seen:
                    continue
                seen.add(b)
                cands.append((r, tid, cname, b))
        with ThreadPoolExecutor(max_workers=12) as ex:
            modes_res = list(ex.map(lambda c: probe_tid(c[0], c[1]), cands))

        buckets, used, modes = {}, {}, {}
        for (r, tid, cname, b), mode in zip(cands, modes_res):
            if used.get(b, 0) >= MAX_SRC_PER_BUCKET:      # 每桶最多 N 源，按排序取前面的
                continue
            used[b] = used.get(b, 0) + 1
            modes[b] = modes.get(b, {})
            modes[b][mode] = modes[b].get(mode, 0) + 1
            q = ('ac=videolist&t=%s&pg={pg}' % tid) if mode == 't' else 'ac=videolist&pg={pg}'
            buckets.setdefault(b, []).append({
                'name': r['name'], 'api': r['api'], 'type': r['type'],
                'tid': tid, 'cname': cname, 'total': int(r.get('_total') or 0),
                'q': q,
            })

        order = GROUP_ORDER[grp]
        kws_map = dict(GROUP_BUCKETS[grp])
        bl = [{'name': b, 'kws': kws_map.get(b, []), 'xkws': BUCKET_XKWS.get(b, []),
               'srcs': buckets[b]} for b in order if buckets.get(b)]
        out[grp] = {'buckets': bl}
        print(f'{grp}: {len(srcs)} 源 → ' +
              ', '.join(f"{b['name']}{len(b['srcs'])}" for b in bl))
        for b, m in modes.items():
            print(f'   {b}: 认 t {m.get("t", 0)} 源 / 只能全量 {m.get("all", 0)} 源')

    save_cache()
    # 自检：抓取抖动时可能所有源都失败，这时宁可保留上一版，也不能写一个空订阅出去
    n_other = len({s['api'] for b in out.get('other', {}).get('buckets', []) for s in b['srcs']})
    n_adult = len({s['api'] for b in out.get('adult', {}).get('buckets', []) for s in b['srcs']})
    if n_other < 5 or n_adult < 3:
        raise SystemExit(f'!! 源数异常（other={n_other} adult={n_adult}），保留上一版 agg_srcs.json')
    json.dump(out, open(os.path.join(DIST, 'agg_srcs.json'), 'w'), ensure_ascii=False)
    print('→ dist2/agg_srcs.json', os.path.getsize(os.path.join(DIST, 'agg_srcs.json')), 'B')


if __name__ == '__main__':
    main()
