#!/usr/bin/env python3
"""统一入口加载器：读 manual_sources.json，产出站点/直播池。

- vod  → manual_vod_sites.json   [{name, api, type, src}]
- live → manual_live.json        [{name, url, src, cc}]

点播配置支持 TVBox JSON（sites 数组）与 TXT（每行 名称,api 或 名称,type,api）。
只保留 type 0/1/4 —— type 3 是 jar/js 爬虫，本机跑不了，加了也是废的。
"""
import json, os, re, sys, time
import urllib.request, urllib.error, urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL = os.path.join(BASE, 'config', 'manual_sources.json')
UA = 'Mozilla/5.0 (Linux; Android 12) okhttp/3.15.0'
TIMEOUT = 25


def fetch(url):
    # 中文域名（如「我不是.摸鱼儿.top」）要先转 punycode，不能只做百分号编码
    try:
        p = urllib.parse.urlsplit(url)
        host = p.hostname or ''
        if any(ord(c) > 127 for c in host):
            netloc = host.encode('idna').decode()
            if p.port:
                netloc += f':{p.port}'
            url = urllib.parse.urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))
    except Exception:
        pass
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
    for enc in ('utf-8', 'gbk', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', 'ignore')


def _brace_objects(text):
    """抠出文本里的站点对象。

    先尝试最外层整体；再取所有「数组元素」层的 {...}（sites:[{..},{..}] 的每个元素），
    这样即使配置里混了注释、Markdown 标题等杂质也能救回可用站点。
    """
    out, depth, starts, in_str, esc = [], 0, {}, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            depth += 1
            starts[depth] = i
        elif ch == '}':
            if depth > 0:
                # depth==2 表示这是数组里的一个元素对象
                if depth == 2 and starts.get(2) is not None:
                    out.append(text[starts[2]:i + 1])
                elif depth == 1 and starts.get(1) is not None:
                    out.append(text[starts[1]:i + 1])
                depth -= 1
    return out


def salvage_sites(text):
    """配置被注释/Markdown 污染时的兜底：逐段尝试解析出站点对象"""
    sites = []
    for frag in _brace_objects(text):
        try:
            d = json.loads(frag)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        if isinstance(d.get('sites'), list):
            sites += [x for x in d['sites'] if isinstance(x, dict)]
        elif d.get('api'):
            sites.append(d)
    return sites


def take_sites(sites, src):
    """从 sites 数组里挑出可测的站点（type 0/1/4）"""
    out = []
    for s in sites:
        if not isinstance(s, dict):
            continue
        api = (s.get('api') or '').strip()
        if not api or not api.startswith('http'):
            continue
        ty = s.get('type')
        if str(ty) not in ('0', '1', '4'):
            continue
        name = (s.get('name') or s.get('key') or '').strip()
        if not name:
            continue
        out.append({'name': name, 'api': api, 'type': int(ty), 'src': src})
    return out


def take_js_sites(sites, src):
    """type 3 且 api 指向 .js 的 drpy 源 —— 走 js 链路，不进采集池"""
    out = []
    for s in sites:
        if not isinstance(s, dict):
            continue
        api = s.get('api') or ''
        ext = s.get('ext') or ''
        if not isinstance(api, str):
            api = ''
        if not isinstance(ext, str):
            ext = ''
        api, ext = api.strip(), ext.strip()
        if not (api.endswith('.js') or '.js' in api):
            continue
        name = (s.get('name') or s.get('key') or '').strip()
        if not name:
            continue
        out.append({'name': name, 'api': api, 'ext': ext, 'src': src})
    return out


def parse_vod(text, src):
    """从 TVBox 配置里抠出 type 0/1/4 的站点。"""
    out = []
    t = text.strip()
    # JSON 配置
    if t.startswith('{') or t.startswith('['):
        d = None
        try:
            d = json.loads(t)
        except Exception:
            d = None
        if d is not None:
            sites = d.get('sites') if isinstance(d, dict) else d
            if isinstance(sites, list):
                return take_sites(sites, src)
        # 兜底：注释/Markdown 污染的配置
        salv = salvage_sites(t)
        if salv:
            return take_sites(salv, src)
        return out
    # TXT 配置：名称,api  或  名称,type,api
    for line in t.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 3 and parts[1] in ('0', '1', '4'):
            name, ty, api = parts[0], int(parts[1]), parts[2]
        elif len(parts) == 2 and parts[1].startswith('http'):
            name, ty, api = parts[0], 1, parts[1]
        else:
            continue
        if not name or not api.startswith('http'):
            continue
        out.append({'name': name, 'api': api, 'type': ty, 'src': src})
    return out


def parse_live(text, src, cc):
    """m3u / txt 直播列表 → [{name, url, src, cc}]"""
    out = []
    if '#EXTINF' in text:
        name, grp = None, ''
        for ln in text.splitlines():
            ln = ln.strip()
            if ln.startswith('#EXTINF'):
                m = re.search(r'group-title="([^"]*)"', ln)
                grp = m.group(1) if m else ''
                name = ln.split(',')[-1].strip()
            elif ln and not ln.startswith('#') and '://' in ln and name:
                out.append({'name': name, 'url': ln.split('$')[0].strip(),
                            'src': src, 'cc': cc, 'grp': grp})
                name = None
    else:
        grp = ''
        for ln in text.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith('#'):
                continue
            if ln.endswith(',#genre#'):
                grp = ln[:-9].strip()
                continue
            if ',' not in ln:
                continue
            name, rest = ln.split(',', 1)
            for u in rest.split('#'):
                u = u.strip()
                if u.startswith('http'):
                    out.append({'name': name.strip(), 'url': u, 'src': src,
                                'cc': cc, 'grp': grp})
    return out


def strip_comments(t):
    """去掉 // 开头的整行注释（多仓 txt 里常见），保留 URL 里的 //"""
    out = []
    for ln in t.splitlines():
        s = ln.strip()
        if s.startswith('//'):
            continue
        out.append(ln)
    return '\n'.join(out)


def parse_config(url, src, depth=0, seen=None):
    """拉一个配置；若是多仓索引则递归展开。返回 (http_sites, js_sites, errors)"""
    if seen is None:
        seen = set()
    if url in seen or depth > 2:
        return [], [], []
    seen.add(url)
    try:
        text = fetch(url)
    except Exception as e:
        return [], [], [f'{src}: {type(e).__name__}']
    t = strip_comments(text).strip()
    if t.startswith('{'):
        d = None
        try:
            d = json.loads(t)
        except Exception:
            d = None
        if d is None:
            salv = salvage_sites(t)
            if not salv:
                return [], [], [f'{src}: JSON 解析失败']
            return take_sites(salv, src), take_js_sites(salv, src), []
        # 多仓：{"urls":[{"name","url"}]}
        if isinstance(d, dict) and isinstance(d.get('urls'), list) and 'sites' not in d:
            hs, js, errs = [], [], []
            for u in d['urls']:
                if isinstance(u, dict) and str(u.get('url', '')).startswith('http'):
                    s2, j2, e2 = parse_config(u['url'], (u.get('name') or src).strip(), depth + 1, seen)
                    hs += s2
                    js += j2
                    errs += e2
            return hs, js, errs
        # 逐段兜底取全量站点，再按 type 分流
        all_sites = []
        if isinstance(d, dict) and isinstance(d.get('sites'), list):
            all_sites = [x for x in d['sites'] if isinstance(x, dict)]
        elif isinstance(d, list):
            all_sites = [x for x in d if isinstance(x, dict)]
        else:
            all_sites = salvage_sites(t)
        return take_sites(all_sites, src), take_js_sites(all_sites, src), []
    return parse_vod(t, src), [], []


def main():
    cfg = json.load(open(MANUAL, encoding='utf-8'))
    vod_all, js_all, live_all, errs = [], [], [], []

    for item in cfg.get('vod', []):
        sites, jss, e = parse_config(item['url'], item.get('src', item['name']))
        vod_all += sites
        js_all += jss
        errs += e
        print(f"  [vod] {item['name']:<18} {len(sites):>4} 采集 + {len(jss):>3} js 站点")

    live_items = [] if '--no-live' in sys.argv else cfg.get('live', [])
    for item in live_items:
        try:
            ch = parse_live(fetch(item['url']), item.get('src', item['name']), item.get('cc', ''))
            live_all += ch
            print(f"  [live] {item['name']:<17} {len(ch):>4} 条")
        except Exception as e:
            errs.append(f"live {item['name']}: {type(e).__name__}")
            print(f"  [live] {item['name']:<17} 失败 {type(e).__name__}")

    # 按 api/url 去重
    seen, uq = set(), []
    for s in vod_all:
        k = s['api'].rstrip('/')
        if k in seen:
            continue
        seen.add(k); uq.append(s)
    seen, ul = set(), []
    for x in live_all:
        k = x['url']
        if k in seen:
            continue
        seen.add(k); ul.append(x)

    seen, uj = set(), []
    for s in js_all:
        k = (s['api'] + '|' + s.get('ext', '')).rstrip('/')
        if k in seen:
            continue
        seen.add(k); uj.append(s)

    json.dump(uq, open(os.path.join(BASE, 'state', 'manual_vod_sites.json'), 'w'),
              ensure_ascii=False, indent=1)
    json.dump(uj, open(os.path.join(BASE, 'state', 'manual_js_sites.json'), 'w'),
              ensure_ascii=False, indent=1)
    if live_items or not os.path.exists(os.path.join(BASE, 'state', 'manual_live.json')):
        json.dump(ul, open(os.path.join(BASE, 'state', 'manual_live.json'), 'w'),
                  ensure_ascii=False, indent=1)
    print(f"\n去重后：采集 {len(uq)} 个，js {len(uj)} 个，直播 {len(ul)} 条线路")
    if errs:
        print('失败:', ', '.join(errs))


if __name__ == '__main__':
    main()
