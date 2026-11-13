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

# 港澳台频道：白名单精确匹配 + 黑名单排除（池里混着「凤凰传奇」「星空传媒」「香港三级」等噪声）
HK_TW_ALLOW = re.compile(
    r'(?:凤凰|鳳凰)(?:资讯|中文|卫视|香港|衛視|美洲)|'
    r'^(?:无线|無綫)(?:新闻|星河|翡翠|明珠|华丽|功夫|娱乐|综艺|亚剧|粤片|戏曲|千禧|J1|翡剧)|'
    r'翡翠台|^翡翠$|黄金翡翠台|华丽翡翠台|翡翠台北美版|明珠台|^明珠$|无线明珠|'
    r'^TVB|TVBPlus|TVB Plus|ViuTV|^Viutv$|香港卫视|澳视澳门|澳门卫视|有线新闻|有线综合|'
    r'HOY|靖天(?:映画|戏剧|资讯)|'
    r'中天新闻|三立(?:新闻|台湾|戏剧)|TVBS(?:亚洲|新闻|News)|东森(?:超视|电影|洋片|综合)|'
    r'纬来(?:体育|育乐|电影|精采)|'
    r'^(?:民視|民视|公視|公视|台視|台视)|寰宇新闻|八大(?:戏剧|综合)|星空卫视|星空衛視'
)
HK_TW_DENY = re.compile(
    r'凤凰传奇|星空传媒|香港三级|火凤凰|黑凤凰|翡翠湾|凤凰古城|入れ墨|学生妹|'
    r'杭州明珠|明珠台测试|石景山|房山|四川|星空购物|仰望星空|星空茶茶|'
    r'易中天|非凡|梁非凡|华视[-－]|'
    r'TVB港剧|香港刑侦|香港院线|香港经典|香港贺岁|TVB悬疑|TVB追剧|TVBaby|iTVB|TVB练习生|'
    r'澳门风云|1930年代'
)
# 港澳台展示顺序：香港 → 台湾 → 澳门
HK_TW_ORDER = ['凤凰资讯', '凤凰中文', '凤凰卫视', '凤凰香港', '翡翠台', '明珠台', '无线新闻',
               '无线星河', 'TVB Plus', 'ViuTV', '香港卫视', '有线新闻', '有线综合', '星空卫视',
               '中天新闻', '三立新闻', 'TVBS亚洲', '东森超视', '东森电影', '东森洋片', '东森综合',
               '纬来体育', '纬来育乐', '纬来电影', '民視', '民视', '台視', '台视', '公視', '公视',
               '靖天映画', '靖天戏剧', '靖天资讯', '澳视澳门', '澳门卫视']

# 港澳台归并：凤凰资讯 / 凤凰资讯频标 / 凤凰资讯 (720p) 是同一个频道
TRAD = str.maketrans({'鳳': '凤', '衛': '卫', '視': '视', '資': '资', '訊': '讯',
                      '綫': '线', '線': '线', '亞': '亚', '臺': '台', '灣': '湾',
                      '無': '无', '聞': '闻', '東': '东', '華': '华', '龍': '龙',
                      '來': '来', '劇': '剧', '綜': '综', '藝': '艺', '體': '体',
                      '樂': '乐', '電': '电', '影': '影', '戲': '戏', '曲': '曲'})
HK_ALIAS = {
    '凤凰中文': '凤凰卫视中文台', '凤凰卫视中文台': '凤凰卫视中文台',
    '凤凰资讯': '凤凰卫视资讯台', '凤凰卫视资讯台': '凤凰卫视资讯台',
    '翡翠': '翡翠台', '无线翡翠': '翡翠台', '黄金翡翠台': '翡翠台',
    '明珠': '明珠台', '无线明珠': '明珠台',
    'viutv': 'ViuTV',
    'tvbs-asia': 'TVBS亚洲', 'tvbs亚洲': 'TVBS亚洲',
    'TVB PLUS': 'TVB Plus',
    '三立台湾': '三立台湾台',
    'tvb翡翠台': '翡翠台', 'tvb明珠台': '明珠台', 'tvb无线新闻': '无线新闻',
    'tvb星河': 'TVB星河',
}

def hk_base(nm):
    b = re.sub(r'\s*[（(].*?[)）]', '', nm).translate(TRAD)
    b = re.sub(r'\[[^\]]*\]', '', b)
    b = b.replace('频标', '').replace('测试', '').strip()
    b = re.sub(r'\s*(1080[pi]|720p|576[pi]|2160p|4k|8k|hd|sd|高清|超清|标清|蓝光)\s*$', '',
               b, flags=re.I).strip()
    b = re.sub(r'^(无线|無綫)', '', b).strip()

    def alias_of(x):
        k = x.lower().replace(' ', '')
        for a, canon_name in HK_ALIAS.items():
            if k == a.lower().replace(' ', ''):
                return canon_name
        return None

    hit = alias_of(b)      # 先查别名（TVB翡翠台 → 翡翠台）
    if hit:
        return hit
    if b.endswith('台') and len(b) > 2:
        b = b[:-1]          # 「新闻台」与「新闻」是同一个频道
    hit = alias_of(b)
    return hit or b

def pick_display(names, key):
    """归并键去掉了「无线」前缀，展示名要把它加回来（否则频道名只剩「新闻」）"""
    canon_vals = {'翡翠台', '明珠台', 'ViuTV', '凤凰卫视中文台', '凤凰卫视资讯台',
                  'TVBS亚洲', '三立台湾台', 'TVB Plus'}
    if key in canon_vals:
        return key
    cands = [re.sub(r'\s*[（(].*?[)）]', '', n).translate(TRAD).strip() for n in names]
    cands = [c for c in cands if c]
    if not cands:
        return key
    with_w = [c for c in cands if c.startswith('无线')]
    pool = sorted(with_w or cands, key=len, reverse=True)
    best = pool[0]
    return best if len(best) <= 12 else key

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
    groups = {'央视': [], '卫视': [], '港澳台': [], '其他': []}
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

    # 港澳台：不受「线路数 ≥3」限制——真频道常常只有一两条源
    def hk_rank(nm):
        base = re.sub(r'\s*\(.*?\)|\s*[（(].*?[)）]', '', nm).strip()
        for i, w in enumerate(HK_TW_ORDER):
            if base == w or base.startswith(w):
                return i
        return 99
    hk = [(k, v, nm, hm) for k, v, nm, hm in items
          if k not in used and HK_TW_ALLOW.search(nm) and not HK_TW_DENY.search(nm)]

    # 归并同名变体（hk_base / pick_display 已提到模块级，供测活脚本复用）


    merged_hk = {}
    for k, v, nm, hm in hk:
        b = hk_base(nm)
        g = merged_hk.setdefault(b, {'routes': [], 'hm': False, 'names': []})
        g['routes'].extend(v)
        g['hm'] = g['hm'] or hm
        g['names'].append(nm)
    hk_items = [(b, g['routes'], pick_display(g['names'], b), g['hm'])
                for b, g in merged_hk.items()]
    hk_items.sort(key=lambda x: (hk_rank(x[2]), -len(x[1])))

    # 港澳台实测（probe_hktw.py）：有数据就只留能播的，全死的频道直接不展示
    hk_tested = {}
    tp_hk = os.path.join(BASE, 'hktw_tested.json')
    if os.path.exists(tp_hk):
        try:
            hk_tested = json.load(open(tp_hk))
        except Exception:
            hk_tested = {}
    if hk_tested:
        print(f'  港澳台实测覆盖 {len(hk_tested)} 个频道')

    for k, v, nm, hm in hk_items:
        t = hk_tested.get(nm)
        if t is not None:
            goods = t.get('good') or []
            if not goods:
                continue                      # 测过且全死
            order = {g['url']: g.get('ms', 99999) for g in goods}
            routed = [r for r in v if r['url'] in order]
            if not routed:
                continue
            routed.sort(key=lambda r: order.get(r['url'], 99999))
            v, hm = routed, True
        ch = build_channel(nm, v, strict=hm)
        if ch:
            groups['港澳台'].append(ch)

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
    print(f'央视 {len(groups["央视"])} | 卫视 {len(groups["卫视"])} | 港澳台 {len(groups["港澳台"])} | 其他 {len(groups["其他"])} → 共 {total}')
    for gname, chs in groups.items():
        for c in chs[:6]:
            print(f'  [{gname}] {c["name"]:18} {len(c["urls"])} 线路  首条来源标签={c["urls"][0].split("$")[-1]}')

    live_groups = [{'name': g, 'channel': chs} for g, chs in groups.items() if chs]
    json.dump(live_groups, open(os.path.join(BASE, 'live_groups.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'\n写入 live_groups.json：{len(live_groups)} 个分组')
