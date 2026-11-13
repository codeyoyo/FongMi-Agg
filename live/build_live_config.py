#!/usr/bin/env python3
"""把 merge 后的频道表生成为 FongMi 内嵌直播分组（每频道多线路，播放器自动 fallback）"""
import json, re, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 源可信度权重：抽样存活率越高越靠前
SRC_RANK = {
    '虎牙一起看': 0, '斗鱼一起看': 0, '肥羊YY轮播': 0, '电视狗': 1, '电视狗 ': 1,
    'Yoursmile': 2, '南风直播源': 2, '直播': 3, 'Guovin': 3,
    '全国组播': 4, '超清测试': 4, 'LIVEfl': 4, '应该能看': 4, '芙蕾测试': 4,
    'iptv-org': 5,
}

CCTV_ORDER = ['cctv1', 'cctv2', 'cctv3', 'cctv4', 'cctv5', 'cctv5+', 'cctv6', 'cctv7', 'cctv8',
              'cctv9', 'cctv10', 'cctv11', 'cctv12', 'cctv13', 'cctv14', 'cctv15', 'cctv16',
              'cctv17', 'cctv4k', 'cctv8k']

WEISHI = ['湖南卫视', '浙江卫视', '江苏卫视', '东方卫视', '北京卫视', '广东卫视', '深圳卫视',
          '安徽卫视', '山东卫视', '天津卫视', '湖北卫视', '河南卫视', '四川卫视', '重庆卫视',
          '辽宁卫视', '黑龙江卫视', '江西卫视', '福建东南卫视', '东南卫视', '河北卫视',
          '山西卫视', '陕西卫视', '云南卫视', '贵州卫视', '广西卫视', '甘肃卫视',
          '新疆卫视', '西藏卫视', '内蒙古卫视', '宁夏卫视', '青海卫视', '海南卫视',
          '吉林卫视', '厦门卫视', '南方卫视', '康巴卫视', '延边卫视', '兵团卫视']

JUNK = ['yy用户', '测试', 'test', '演示', 'demo', '备用', '未分类', '空', 'unknown',
        'null', 'undefined', '用户', '收费', '付费', '广告', '推广']

MAX_ROUTES = 6          # 每频道最多保留线路数（多了配置臃肿）
MAX_CHANNELS = 400      # 总频道上限


def clean_name(n):
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def cctv_key(name):
    s = re.sub(r'[\s\-_]', '', name).lower()
    m = re.match(r'cctv(\d+)(\+|plus)?', s)
    if m:
        return 'cctv' + m.group(1) + ('+' if m.group(2) else '')
    return None


NOISE = ['高清', '超清', '蓝光', '标清', 'hd', 'hd版', '高清版', '4k', '8k', '-', '_', ' ',
         '频道', '综合', '综艺', '套', '台', '『', '』', '[', ']', '(', ')']


def canon(name):
    """把各源五花八门的命名归一：CCTV-1综合 / CCTV1 / CCTV-1HD → cctv1"""
    ck = cctv_key(name)
    if ck:
        return ck
    n = re.sub(r'[\s\-_·・]', '', name).lower()
    for w in NOISE:
        n = n.replace(w, '')
    return n


def pick_channels(merged, tested):
    """返回 {分组名: [Channel, ...]}"""
    groups = {'央视': [], '卫视': [], '其他': []}
    tested_urls = {}
    for k, v in (tested or {}).items():
        tested_urls[k] = set(v.get('routes') or [])

    # 先把同一频道的多个命名合并
    buckets = {}
    for key, routes in merged.items():
        ck = canon(routes[0]['name'])
        b = buckets.setdefault(ck, {'name': routes[0]['name'], 'routes': [], 'keys': [], 'ck': ck})
        b['keys'].append(key)
        # 名称优先选短的（CCTV-1 优于 CCTV-1综合），卫视优先带「卫视」的
        nm = routes[0]['name']
        if len(nm) < len(b['name']) and '综合' not in nm:
            b['name'] = nm
        b['routes'].extend(routes)

    items = []
    for ck, b in buckets.items():
        seen, uniq = set(), []
        for r in b['routes']:
            u = r['url'].strip()
            if u in seen:
                continue
            seen.add(u)
            uniq.append(r)
        if not uniq:
            continue
        good = set()
        # 归并后的 key（cctv1）与原始 key（cctv-1综合）都要查
        for k in list(b['keys']) + [b.get('ck')]:
            if k:
                good |= tested_urls.get(k, set())
        if good:
            # 有实测数据 → 只留能播的，并按实测耗时排
            measured = [r for r in uniq if r['url'] in good]
            if measured:
                uniq = measured
        uniq.sort(key=lambda r: (0 if r['url'] in good else 1, SRC_RANK.get(r['src'].strip(), 9)))
        items.append((ck, uniq, b['name'], bool(good)))

    # 央视
    cctv = [(k, v, nm, hm) for k, v, nm, hm in items if cctv_key(nm)]

    def cctv_rank(kv):
        ck = cctv_key(kv[2])
        try:
            return CCTV_ORDER.index(ck)
        except ValueError:
            return 99
    cctv.sort(key=cctv_rank)

    used = set()
    for k, v, nm, hm in cctv:
        ch = build_channel(nm, v, strict=hm)
        if ch:
            groups['央视'].append(ch); used.add(k)

    # 卫视：按规范化名匹配
    wmap = {canon(w): w for w in WEISHI}
    ws = [(k, v, nm, hm) for k, v, nm, hm in items if k in wmap and k not in used]
    order = {canon(w): i for i, w in enumerate(WEISHI)}
    ws.sort(key=lambda x: order.get(x[0], 99))
    for k, v, nm, hm in ws:
        ch = build_channel(wmap[k], v, strict=hm)
        if ch:
            groups['卫视'].append(ch); used.add(k)

    # 其他：剩余里线路数 ≥3 的（说明多源收录，较可靠）
    def junk(nm):
        low = nm.lower()
        return any(w in low for w in JUNK)

    rest = [(k, v, nm, hm) for k, v, nm, hm in items if k not in used and len(v) >= 3 and not junk(nm)]
    rest.sort(key=lambda x: -len(x[1]))
    for k, v, nm, hm in rest[:MAX_CHANNELS - len(groups['央视']) - len(groups['卫视'])]:
        ch = build_channel(nm, v, strict=hm)
        if ch:
            groups['其他'].append(ch)

    return groups


def build_channel(display_name, routes, strict=False):
    """每源最多取 2 条 —— 避免 6 条线路全来自同一个源，源挂了就整频道失效"""
    urls, per_src = [], {}
    for r in routes:
        tag = r['src'].strip()[:8].replace('$', '')
        if per_src.get(tag, 0) >= 2:
            continue
        per_src[tag] = per_src.get(tag, 0) + 1
        urls.append('%s$%s' % (r['url'], tag))
        if len(urls) >= MAX_ROUTES:
            break
    # 严格模式（有实测数据）：绝不补未验证线路
    if strict:
        return {'name': clean_name(display_name), 'urls': urls} if urls else None
    # 如果源太少凑不满，再放宽一次
    if len(urls) < MAX_ROUTES:
        for r in routes:
            u = '%s$%s' % (r['url'], r['src'].strip()[:8].replace('$', ''))
            if u in urls:
                continue
            urls.append(u)
            if len(urls) >= MAX_ROUTES:
                break
    if not urls:
        return None
    return {'name': clean_name(display_name), 'urls': urls}


if __name__ == '__main__':
    merged = json.load(open(os.path.join(BASE, 'live_merged.json')))
    tested = {}
    # 1) 批量实测结果（最权威）
    ta = os.path.join(BASE, 'live_route_test_all.json')
    if os.path.exists(ta):
        for k, v in json.load(open(ta)).items():
            if v.get('good'):
                tested[k] = {'name': '', 'routes': [g['url'] for g in v['good']]}
        print(f'  使用批量实测: {len(tested)} 个频道有可用线路')
    # 2) 早先的单频测试补充
    tp = os.path.join(BASE, 'live_tested_core.json')
    if os.path.exists(tp):
        for k, v in json.load(open(tp)).items():
            if k not in tested and v.get('routes'):
                tested[k] = v

    groups = pick_channels(merged, tested)
    total = sum(len(v) for v in groups.values())
    print(f'央视 {len(groups["央视"])} | 卫视 {len(groups["卫视"])} | 其他 {len(groups["其他"])} → 共 {total}')
    for gname, chs in groups.items():
        for c in chs[:6]:
            print(f'  [{gname}] {c["name"]:18} {len(c["urls"])} 线路  首条来源标签={c["urls"][0].split("$")[-1]}')

    live_groups = [{'name': g, 'channel': chs} for g, chs in groups.items() if chs]
    json.dump(live_groups, open(os.path.join(BASE, 'live_groups.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'\n写入 live_groups.json：{len(live_groups)} 个分组')
