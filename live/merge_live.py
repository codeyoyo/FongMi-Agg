#!/usr/bin/env python3
"""把通过抽样的直播源合并成「按频道名归并、每频道挂多线路」的结构"""
import json, os, re, ssl, urllib.request, concurrent.futures as cf
from collections import defaultdict

UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE


def fetch(url, timeout=25, limit=8_000_000):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read(limit).decode('utf-8', 'ignore')


def parse(text):
    """返回 [(name, url, group)]"""
    out = []
    if '#EXTINF' in text:
        cur_name, cur_grp = None, ''
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith('#EXTINF'):
                m = re.search(r'group-title="([^"]*)"', line)
                cur_grp = m.group(1) if m else ''
                cur_name = line.split(',')[-1].strip()
            elif line.startswith('#'):
                continue
            elif '://' in line and cur_name:
                out.append((cur_name, line.split('$')[0].strip(), cur_grp))
                cur_name = None
    else:
        grp = ''
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '#genre#' in line:
                grp = line.split(',')[0].strip()
                continue
            if line.split(',')[0].strip() in ('ua', 'referer', 'format', 'parse', 'click', 'header', 'origin', 'forceKey'):
                continue
            parts = line.split(',', 1)
            if len(parts) < 2:
                continue
            name = parts[0].strip()
            for u in parts[1].split('#'):
                u = u.split('$')[0].strip()
                if '://' in u:
                    out.append((name, u, grp))
    return out


if __name__ == '__main__':
    kept = json.load(open('/app/working/fongmi-agg/clbug_live_kept.json'))
    # 补上 Guovin / iptv-org
    kept += [
        {'name': 'Guovin', 'url': 'https://cdn.jsdelivr.net/gh/Guovin/iptv-api@gd/output/result.m3u'},
        {'name': 'iptv-org', 'url': 'https://cdn.jsdelivr.net/gh/iptv-org/iptv@master/streams/cn.m3u'},
    ]
    # URL 去重
    seen, srcs = set(), []
    for k in kept:
        if k['url'] in seen:
            continue
        seen.add(k['url']); srcs.append(k)
    print(f'合并 {len(srcs)} 个直播源\n')

    def get_one(s):
        try:
            return s['name'], parse(fetch(s['url']))
        except Exception as e:
            print(f'  ✗ {s["name"]}: {type(e).__name__}')
            return s['name'], []

    with cf.ThreadPoolExecutor(8) as ex:
        results = list(ex.map(get_one, srcs))

    # 统一入口 manual_sources.json 的直播源（load_manual.py 已解析成频道级）
    mp = '/app/working/fongmi-agg/manual_live.json'
    if os.path.exists(mp):
        manual = json.load(open(mp))
        results.append(('manual', [(x['name'], x['url'], x.get('grp', '')) for x in manual]))
        print(f'  {len(manual):>6} 频道  manual（统一入口）')

    by_name = defaultdict(list)
    total = 0
    for sname, chans in results:
        print(f'  {len(chans):>6} 频道  {sname}')
        total += len(chans)
        for name, url, grp in chans:
            key = re.sub(r'\s+', '', name).lower()
            if not key:
                continue
            by_name[key].append({'name': name, 'url': url, 'src': sname, 'grp': grp})

    print(f'\n原始 {total} 条 → 唯一频道名 {len(by_name)} 个')
    multi = sum(1 for v in by_name.values() if len(v) > 1)
    print(f'有多线路冗余的频道: {multi}')

    dist = defaultdict(int)
    for v in by_name.values():
        dist[min(len(v), 10)] += 1
    print('线路数分布(≥10 归并):', dict(sorted(dist.items())))

    # 央视/卫视优先
    cctv = [k for k in by_name if re.match(r'cctv', k) or 'cctv' in k]
    weishi = [k for k in by_name if any(w in k for w in ['卫视', '湖南', '东方', '浙江', '江苏', '北京', '广东', '深圳', '安徽', '山东', '天津', '湖北', '河南', '四川', '重庆', '辽宁', '黑龙江', '江西', '福建', '河北', '山西', '陕西', '云南', '贵州', '广西', '甘肃', '新疆', '西藏', '内蒙古', '宁夏', '青海', '海南', '吉林'])]
    print(f'\n央视频道 {len(cctv)} 个 | 卫视/省台 {len(weishi)} 个')

    print('\n--- 线路最多的 25 个频道 ---')
    for k, v in sorted(by_name.items(), key=lambda x: -len(x[1]))[:25]:
        print(f'  {len(v):>3} 线路  {v[0]["name"][:30]}')

    json.dump({k: v for k, v in by_name.items()},
              open('/app/working/fongmi-agg/live_merged.json', 'w'), ensure_ascii=False, indent=1)
