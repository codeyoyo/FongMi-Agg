#!/usr/bin/env python3
"""probe_classes.py —— 拉每个采集站的分类名列表（?ac=list），用于更准的内容判定

标题抽样误判率高（正经大站也会出现"三级""情色"等片名），
分类名（class）才是站点的自我定位，判据更稳。
"""
import json, os, re, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 12)'}


def get_classes(site):
    api, typ = str(site.get('api') or ''), site.get('type')
    sep = '&' if '?' in api else '?'
    url = api + sep + ('ac=list&at=xml' if typ == 0 else 'ac=list')
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=12) as r:
            body = r.read(200000).decode('utf-8', 'ignore')
    except Exception as e:
        return {**site, '_classes': [], '_cerr': type(e).__name__}

    names = []
    if typ == 0:
        names = re.findall(r'<ty[^>]*>(.*?)</ty>', body) or \
                re.findall(r'<name><!\[CDATA\[(.*?)\]\]></name>', body)
    else:
        try:
            j = json.loads(body)
            for c in (j.get('class') or []):
                if isinstance(c, dict):
                    names.append(str(c.get('type_name') or c.get('type_id') or ''))
                else:
                    names.append(str(c))
        except Exception as e:
            return {**site, '_classes': [], '_cerr': 'json:' + type(e).__name__}
    names = [n.strip() for n in names if str(n).strip()]
    return {**site, '_classes': names[:60]}


def main():
    pool = json.load(open(os.path.join(BASE, 'state', 'ok_api_final.json')))
    try:
        extra = [{'name': s['name'].strip(), 'type': s['type'], 'api': s['api'],
                  '_total': s.get('total', 0)} for s in json.load(open(os.path.join(BASE, 'clbug_clean.json')))]
        seen = {str(x['api']) for x in pool}
        pool += [x for x in extra if str(x['api']) not in seen]
    except FileNotFoundError:
        pass

    with ThreadPoolExecutor(max_workers=8) as ex:
        out = list(ex.map(get_classes, pool))
    json.dump(out, open(os.path.join(BASE, 'state', 'classes_all.json'), 'w'),
              ensure_ascii=False, indent=1)
    ok = [x for x in out if x.get('_classes')]
    print(f'{len(ok)}/{len(out)} 拿到分类名')
    for x in out[:8]:
        print(f"  {x['name'][:12]:<14} {x.get('_cerr','')} {x.get('_classes')[:12]}")


if __name__ == '__main__':
    main()
