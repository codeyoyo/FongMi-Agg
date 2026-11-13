#!/usr/bin/env python3
"""clbug 池：成人过滤 + 片库去重 + 三层验证"""
import json, re, ssl, urllib.request, concurrent.futures as cf

UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

ADULT_WORDS = ['🔞', '麻豆', '番号', '黑料', '色南国', '美少女', '91精品', '91麻豆',
               '成人', '情色', '涩', '无码', 'AV', '必看', 'av视频']


def get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read(800000).decode('utf-8', 'ignore')


def jget(url, timeout=15):
    return json.loads(get(url, timeout))


def is_adult_name(name):
    return any(w in str(name) for w in ADULT_WORDS)


def l1(api, typ):
    """分类层"""
    sep = '&' if '?' in api else '?'
    try:
        j = jget(api + sep + 'ac=list')
        cls = j.get('class') or []
        if cls:
            return True, [c.get('type_name') or c.get('type_id') for c in cls[:30]]
    except Exception:
        pass
    return False, []


def sample_titles(api, typ, cls):
    """取首个分类前 20 条标题，用于成人判定"""
    sep = '&' if '?' in api else '?'
    tid = None
    try:
        j = jget(api + sep + 'ac=list')
        c = (j.get('class') or [{}])[0]
        tid = c.get('type_id') or c.get('type')
    except Exception:
        return []
    if tid is None:
        return []
    tries = [api + sep + 'ac=videolist&t=%s&pg=1' % tid,
             api + sep + 'ac=detail&t=%s&pg=1' % tid,
             api + sep + 'ac=videolist&pg=1']
    for u in tries:
        try:
            j = jget(u)
            lst = j.get('list') or []
            return [str(v.get('vod_name') or '') for v in lst[:20]]
        except Exception:
            continue
    return []


def l2(api, typ):
    """列表层：能否拿到视频列表"""
    sep = '&' if '?' in api else '?'
    for u in (api + sep + 'ac=videolist&pg=1', api + sep + 'ac=detail&pg=1'):
        try:
            j = jget(u)
            lst = j.get('list') or []
            if lst and str(lst[0].get('vod_id')) != 'no_data':
                return True, lst
        except Exception:
            continue
    return False, []


def l3(api, typ, vod_id):
    """详情层"""
    sep = '&' if '?' in api else '?'
    try:
        j = jget(api + sep + 'ac=detail&ids=%s' % vod_id)
        lst = j.get('list') or []
        if lst:
            v = lst[0]
            return bool(v.get('vod_play_url')), str(v.get('vod_name') or '')
    except Exception:
        pass
    return False, ''


def evaluate(s):
    api = str(s['api'])
    if '?' not in api and not api.endswith('/'):
        api += '/'
    r = dict(s, api=api, adult=False, pass3=False, titles=[], reason='')
    ok1, cls = l1(api, s['type'])
    if not ok1:
        r['reason'] = 'L1 分类不通过'
        return r
    titles = sample_titles(api, s['type'], cls)
    r['titles'] = titles[:6]
    # 成人判定：标题抽样命中率
    hits = sum(1 for t in titles if any(w in t for w in ['麻豆', '无码', '中字', '偷拍', '强', '淫', '女优']))
    if titles and hits / max(1, len(titles)) > 0.2:
        r['adult'] = True
        r['reason'] = '内容抽样 %d/%d 疑似成人' % (hits, len(titles))
        return r
    if is_adult_name(s['name']):
        r['adult'] = True
        r['reason'] = '站名命中成人关键词'
        return r
    ok2, lst = l2(api, s['type'])
    if not ok2:
        r['reason'] = 'L2 列表不通过'
        return r
    vid = lst[0].get('vod_id')
    ok3, title = l3(api, s['type'], vid)
    if not ok3:
        r['reason'] = 'L3 详情无播放地址'
        return r
    r['pass3'] = True
    r['sample'] = title
    return r


if __name__ == '__main__':
    probe = json.load(open('/app/working/fongmi-agg/clbug_probe.json'))
    passed = [p for p in probe if p['ok']]
    # 先按站名粗筛成人
    clean_name = [p for p in passed if not is_adult_name(p['name'])]
    print(f'测活通过 {len(passed)} → 站名过滤成人后 {len(clean_name)}')
    for p in passed:
        if is_adult_name(p['name']):
            print(f'  [成人-站名] {p["name"][:24]}')

    # 按片库量去重（同 total 视为同一片库，保留最快的）
    bucket = {}
    for p in clean_name:
        key = p['total'] if p['total'] > 0 else ('xml', p['pages'])
        cur = bucket.get(key)
        if not cur or p['ms'] < cur['ms']:
            bucket[key] = p
    dedup = list(bucket.values())
    print(f'\n按片库去重后: {len(dedup)}')

    print('\n三层验证中...')
    with cf.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(evaluate, dedup))

    good = [r for r in res if r['pass3']]
    adult = [r for r in res if r['adult']]
    bad = [r for r in res if not r['pass3'] and not r['adult']]
    print(f'\n✅ 三层全通: {len(good)}')
    for r in sorted(good, key=lambda x: -x['total']):
        print(f"  {r['total']:>8}部  {r['name'][:22]:24} {r['api'][:50]}")
        print(f"            样例: {r.get('sample','')[:30]} | 首分类样本: {' / '.join(t[:12] for t in r['titles'][:3])}")
    print(f'\n🚫 内容判成人: {len(adult)}')
    for r in adult:
        print(f"  {r['name'][:24]:26} {r['reason']}")
    print(f'\n❌ 验证未过: {len(bad)}')
    for r in bad:
        print(f"  {r['name'][:24]:26} {r['reason']}")

    json.dump(good, open('/app/working/fongmi-agg/clbug_clean.json', 'w'), ensure_ascii=False, indent=1)
