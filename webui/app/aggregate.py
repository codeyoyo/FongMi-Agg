#!/usr/bin/env python3
"""本机聚合服务 —— deploy/_worker.js 的 Python 实现

FongMi type=1 站点的四种请求形态与 Cloudflare Worker 完全一致：
  GET /movie                         -> {"class":[...]}
  GET /movie?ac=detail&t=电影&pg=1    -> {"list":[...]}
  GET /movie?ac=detail&ids=s0|123     -> {"list":[{...vod_play_url}]}
  GET /movie?wd=斗罗&quick=true       -> {"list":[...]}

/movie 与 /other 同组（影视资源），/adult 为成人组。
Cloudflare 用 deploy/_worker.js；本机用这份 Python 实现，两边的协议要同步改。
"""
import html
import json
import math
import os
import re
import socket
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from ipaddress import ip_address

_HERE = os.path.dirname(os.path.abspath(__file__))
_HOME = os.path.dirname(_HERE)
_PARENT = os.path.dirname(_HOME)
# 仓库根：本仓库里 webui/ 的上一级；容器里 admin 是独立副本，
# 上一级没有 pipeline/，回退到 /app/working/fongmi-agg。
BASE = os.environ.get('FONGMI_REPO') or (
    _PARENT if os.path.isdir(os.path.join(_PARENT, 'pipeline')) else '/app/working/fongmi-agg')
DIST2 = os.path.join(BASE, 'dist2')
CONFIG = os.path.join(BASE, 'config')

TIMEOUT = 4.0
SEARCH_TIMEOUT = 2.5
DETAIL_TIMEOUT = 5.0
LINE_TIMEOUT = 1.5
BATCH = 10
MAX_ITEMS = 80
UA = 'Mozilla/5.0 (Linux; Android 12)'


# ---------- 出站 URL 安全校验 ----------
# 聚合源和播放地址都来自外部 JSON，不能直接当可信 URL 用。
# 只允许 http/https，拒绝 localhost / 私有 / 环回 / 链路本地 / 保留地址。
_SAFE_CACHE = {}


def _safe_url(url):
    try:
        p = urllib.parse.urlsplit(str(url))
    except Exception:
        return False
    if p.scheme not in ('http', 'https') or not p.hostname:
        return False
    host = p.hostname.strip('[]').lower()
    if host == 'localhost' or host.endswith(('.local', '.internal', '.lan')):
        return False
    if host in _SAFE_CACHE:
        return _SAFE_CACHE[host]
    try:
        ip = ip_address(host)
        ok = not (ip.is_private or ip.is_loopback or ip.is_link_local
                  or ip.is_reserved or ip.is_multicast or ip.is_unspecified)
    except ValueError:
        ok = True
        try:
            for info in socket.getaddrinfo(host, None):
                ip = ip_address(info[4][0])
                if (ip.is_private or ip.is_loopback or ip.is_link_local
                        or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                    ok = False
                    break
        except Exception:
            pass          # 解析失败就交给 fetch 自己报错，不因 DNS 抖动丢源
    if len(_SAFE_CACHE) > 512:
        _SAFE_CACHE.clear()
    _SAFE_CACHE[host] = ok
    return ok


# ---------- 基础工具 ----------

def _run_batched(fn, items, workers=BATCH):
    """按批并发，保持结果顺序；对应 worker 的 runBatched"""
    items = list(items)
    out = []
    if not items:
        return out
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as ex:
        for i in range(0, len(items), workers):
            out.extend(ex.map(fn, items[i:i + workers]))
    return out


def fetch_text(url, ms=None):
    if not _safe_url(url):
        return None
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    try:
        with urllib.request.urlopen(req, timeout=float(ms or TIMEOUT)) as r:
            if getattr(r, 'status', 200) >= 400:
                return None
            return r.read(3_000_000).decode('utf-8', 'ignore')
    except Exception:
        return None


def join_api(api, query):
    """有些源地址自带 ?ac=list，必须把旧 query 剥掉再拼，否则 ac 参数重复"""
    base = str(api).split('?')[0]
    return base + '?' + query


def _txt(x):
    if x is None:
        return ''
    s = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', str(x), flags=re.S)
    s = re.sub(r'<[^>]+>', '', s)
    return html.unescape(s).strip()


def parse_xml_videos(body):
    out = []
    for m in re.finditer(r'<video>(.*?)</video>', body or '', re.S):
        seg = m.group(1)

        def get(tag):
            r = re.search(r'<%s[^>]*>(.*?)</%s>' % (tag, tag), seg, re.S)
            return _txt(r.group(1)) if r else ''

        # XML 站的播放地址在 <dl><dd flag="线路名">名$地址#名$地址</dd></dl> 里，
        # 不是 JSON 风格的 <vod_play_url>；不解析这里，type=0 站点的播放都是空的。
        x_from, x_url = '', ''
        dl = re.search(r'<dl>(.*?)</dl>', seg, re.S)
        if dl:
            froms, urls, n = [], [], 0
            for d in re.finditer(r'<dd([^>]*)>(.*?)</dd>', dl.group(1), re.S):
                text = _txt(d.group(2))
                if not text:
                    continue
                fm = re.search(r'flag="([^"]*)"', d.group(1))
                n += 1
                froms.append((fm.group(1).strip() if fm else '') or '线路%d' % n)
                urls.append(text)
            x_from = '$$$'.join(froms)
            x_url = '$$$'.join(urls)
        out.append({
            'vod_id': get('id'),
            'vod_name': get('name'),
            'vod_pic': get('pic'),
            'vod_remarks': get('note') or get('last'),
            'vod_year': get('year'),
            'vod_area': get('area'),
            'vod_actor': get('actor'),
            'vod_director': get('director'),
            'type_name': get('type'),
            'vod_content': get('des'),
            'vod_play_from': x_from,
            'vod_play_url': x_url,
        })
    return out


def parse_xml_classes(body):
    out = []
    seg = re.search(r'<class>(.*?)</class>', body or '', re.S)
    text = seg.group(1) if seg else (body or '')
    for m in re.finditer(r'<ty\s+id="([^"]+)"\s*>(.*?)</ty>', text, re.S):
        out.append({'type_id': m.group(1).strip(), 'type_name': _txt(m.group(2))})
    return out


def pull(src, query, ms=None):
    q = query + ('&at=xml' if src.get('type') == 0 else '')
    body = fetch_text(join_api(src.get('api', ''), q), ms)
    if not body:
        return None
    if src.get('type') == 0 or body.lstrip().startswith('<'):
        return {'kind': 'xml', 'body': body}
    try:
        return {'kind': 'json', 'data': json.loads(body)}
    except Exception:
        return None


def _list_of(r):
    if not r:
        return []
    if r.get('kind') == 'xml':
        return parse_xml_videos(r.get('body'))
    data = r.get('data')
    lst = data.get('list') if isinstance(data, dict) else None
    return [x for x in (lst or []) if isinstance(x, dict)]


def line_ok(url):
    """m3u8 前 2KB 以 #EXTM3U/#EXTINF/#EXT-X 开头才算活"""
    if not _safe_url(url):
        return False
    req = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Range': 'bytes=0-2047', 'Accept': '*/*'})
    try:
        with urllib.request.urlopen(req, timeout=LINE_TIMEOUT) as r:
            if getattr(r, 'status', 200) >= 400:
                return False
            text = r.read(2048).decode('utf-8', 'ignore').lstrip()
            return text.startswith(('#EXTM3U', '#EXTINF', '#EXT-X'))
    except Exception:
        return False


# ---------- 组数据 ----------

def load_group(name):
    path = os.path.join(DIST2, 'agg_srcs.json')
    try:
        with open(path, encoding='utf-8') as fh:
            return (json.load(fh) or {}).get(name)
    except Exception:
        return None


def load_artifact_defs():
    for p in (os.path.join(CONFIG, 'artifacts.json'),
              os.path.join(DIST2, 'artifacts.json')):
        try:
            with open(p, encoding='utf-8') as fh:
                return (json.load(fh) or {}).get('artifacts') or []
        except Exception:
            continue
    return []


def scope_by_artifact(g, mode):
    """?m=<产物id>：只保留该产物勾选的分类桶。
    产物里没有当前组的分类时原样返回，别把整组筛空（混合产物会同时含影视/成人）。"""
    if not g or not mode:
        return g
    defs = load_artifact_defs()
    d = next((a for a in defs if a.get('id') == mode or a.get('file') == mode + '.json'), None)
    if not d:
        return g
    want = d.get('buckets')
    if want == 'all' or not isinstance(want, list):
        return g
    names = {b.get('name') for b in (g.get('buckets') or [])}
    if not any(n in names for n in want):
        return g
    return {**g, 'buckets': [b for b in (g.get('buckets') or []) if b.get('name') in want]}


def unique_srcs(g):
    """同一组里去重后的源列表；s<idx> 的全局下标由这个顺序决定"""
    seen, out = set(), []
    for b in (g.get('buckets') or []):
        for s in (b.get('srcs') or []):
            api = s.get('api')
            if not api or api in seen:
                continue
            seen.add(api)
            out.append(s)
    return out


def interleave(groups):
    """各源轮流各出一条，避免被片库最大的站整页淹没"""
    out, seen = [], set()
    cursor = [0] * len(groups)
    added = True
    while added and len(out) < MAX_ITEMS:
        added = False
        for i, g in enumerate(groups):
            if not g or len(out) >= MAX_ITEMS:
                continue
            items = g.get('items') or []
            while cursor[i] < len(items):
                it = items[cursor[i]]
                cursor[i] += 1
                if not it:
                    continue
                name = str(it.get('vod_name') or '').strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append({**it, 'vod_id': 's%s|%s' % (g.get('idx'), it.get('vod_id', ''))})
                added = True
                break
    return out


# ---------- 三种协议 ----------

def handle_list(g):
    classes = [{'type_id': '全部', 'type_name': '全部'}]
    classes += [{'type_id': b.get('name'), 'type_name': b.get('name')}
                for b in (g.get('buckets') or [])]
    return {'class': classes, 'filters': {}}


def handle_category(g, bucket_name, pg, debug=False):
    all_srcs = unique_srcs(g)
    idx_of = {s.get('api'): i for i, s in enumerate(all_srcs)}
    want_all = bucket_name == '全部'
    bucket = None if want_all else next(
        (b for b in (g.get('buckets') or []) if b.get('name') == bucket_name), None)
    # 分类聚合的正确姿势：每个源用它自己站点里这个分类的 tid 去拉，
    # 而不是拉站点首页再本地过滤（一页 20 条里常常只有 2-3 条属于该分类）
    srcs = (bucket.get('srcs') or []) if bucket else all_srcs

    def task(src):
        t0 = time.time()
        idx = idx_of.get(src.get('api'), -1)
        q = (str(src.get('q')).replace('{pg}', str(pg))
             if (not want_all and src.get('q')) else 'ac=videolist&pg=%s' % pg)
        r = pull(src, q)
        if not r:
            return {'idx': idx, 'items': [], 'pagecount': 1,
                    'stats': {'i': idx, 'n': -1, 'ms': int((time.time() - t0) * 1000),
                              'name': src.get('name')}}
        if r.get('kind') == 'xml':
            items, pc = parse_xml_videos(r.get('body')), 1
        else:
            data = r.get('data') or {}
            items = [x for x in (data.get('list') or []) if isinstance(x, dict)]
            total = int(data.get('total') or 0)
            pc = int(data.get('pagecount') or (math.ceil(total / 20) if total else 1))
        final = items
        if not want_all:
            kws = (bucket or {}).get('kws') or []
            xkws = (bucket or {}).get('xkws') or []
            if kws or xkws:
                typed = [it for it in items if str(it.get('type_name') or '').strip()]
                if typed:
                    def keep(it):
                        t = str(it.get('type_name') or '')
                        if any(k in t for k in xkws):
                            return False
                        if not kws:
                            return True
                        return any(k in t for k in kws)
                    # 注意过滤的是 items 而不是 typed：「其它」桶只有排除词时，
                    # 没有 type_name 的条目按 worker 语义要保留
                    final = [it for it in items if keep(it)]
        return {'idx': idx, 'items': final, 'pagecount': pc,
                'stats': {'i': idx, 'n': len(items), 'hit': len(final),
                          'ms': int((time.time() - t0) * 1000), 'name': src.get('name'),
                          'tid': src.get('tid'), 'pc': pc}}

    results = _run_batched(task, srcs)
    pcs = sorted(r['pagecount'] for r in results if r and r.get('pagecount', 0) > 0)
    # 各源自报页数差异极大（几十到上万），取中位数，别让单个站把总页数顶到 6000
    pagecount = pcs[len(pcs) // 2] if pcs else 1
    items = interleave([r for r in results if r])
    body = {'list': items, 'page': pg, 'pagecount': pagecount,
            'limit': len(items), 'total': pagecount * len(items)}
    if debug:
        body['debug'] = [r['stats'] for r in results if r]
    return body


def handle_search(g, wd, pg):
    # 全源并发太慢（25 源 ≈ 10s），搜索只打片库最大的前 15 个
    srcs = unique_srcs(g)[:15]

    def task(pair):
        idx, src = pair
        r = pull(src, 'wd=%s&ac=videolist&pg=%s' % (urllib.parse.quote(wd, safe=''), pg))
        if not r:
            return None
        return {'idx': idx, 'items': _list_of(r)}

    results = _run_batched(task, list(enumerate(srcs)))
    items = []
    for r in results:
        if not r:
            continue
        items += [{**it, 'vod_id': 's%s|%s' % (r['idx'], it.get('vod_id', ''))}
                  for it in r['items']]
    return {'list': items, 'page': pg, 'pagecount': 1,
            'limit': len(items), 'total': len(items)}


def _extras_for(item, all_srcs):
    """同一部片去其他源找同名，把播放线路并成一排"""
    name = str(item.get('vod_name') or '').strip()
    if not name:
        return []
    others = [(s, i) for i, s in enumerate(all_srcs) if i != item.get('_idx')]

    def search_one(pair):
        s, _i = pair
        r = pull(s, 'wd=%s&ac=videolist&pg=1' % urllib.parse.quote(name, safe=''),
                 SEARCH_TIMEOUT)
        if not r:
            return None
        hit = next((x for x in _list_of(r)
                    if str(x.get('vod_name') or '').strip() == name), None)
        return {'s': s, 'vid': hit.get('vod_id')} if hit else None

    hits = [x for x in _run_batched(search_one, others) if x]

    def detail_one(h):
        d = pull(h['s'], 'ac=detail&ids=%s' % urllib.parse.quote(str(h['vid']), safe=''),
                 DETAIL_TIMEOUT)
        lst = _list_of(d)
        one = lst[0] if lst else None
        if not one or not one.get('vod_play_url'):
            return None
        froms = str(one.get('vod_play_from') or h['s'].get('name') or '').strip()
        return {'from': froms or h['s'].get('name', ''), 'url': one['vod_play_url']}

    return [x for x in _run_batched(detail_one, hits) if x]


def handle_detail(g, ids):
    want = [x for x in str(ids).split(',') if x]
    all_srcs = unique_srcs(g)
    by_src = {}
    for raw in want:
        m = re.match(r'^s(\d+)\|(.*)$', raw, re.S)
        if not m:
            continue
        by_src.setdefault(int(m.group(1)), []).append(m.group(2))

    primary = []
    for idx, vids in by_src.items():
        if idx >= len(all_srcs):
            continue
        src = all_srcs[idx]
        # 主源是唯一必须成功的：它超时整个详情就空，所以给更长超时并重试一次
        dq = 'ac=detail&ids=' + urllib.parse.quote(','.join(vids), safe='')
        r = pull(src, dq, DETAIL_TIMEOUT) or pull(src, dq, DETAIL_TIMEOUT)
        for it in _list_of(r):
            primary.append({**it, '_idx': idx})
    if not primary:
        return {'list': []}

    probed = []
    for it in primary:
        lines = [{'from': str(it.get('vod_play_from') or '线路1').strip(),
                  'url': it.get('vod_play_url')}]
        lines += _extras_for(it, all_srcs)
        uniq, seen_from = [], set()
        for l in lines:
            if not l.get('url') or l['from'] in seen_from:
                continue
            seen_from.add(l['from'])
            uniq.append(l)

        def check(l):
            first = str(l['url']).split('#')[0].split('$')[-1]
            return {**l, 'ok': line_ok(first)}

        checks = _run_batched(check, uniq)
        good = [x for x in checks if x['ok']]
        # 死的不返回，只在全死时保留首条兜底（总比详情空白强）
        probed.append(good if good else uniq[:1])

    out = []
    for it, lines in zip(primary, probed):
        out.append({
            **it,
            'vod_play_from': '$$$'.join(l['from'] for l in lines),
            'vod_play_url': '$$$'.join(l['url'] for l in lines),
            'vod_id': 's%s|%s' % (it.get('_idx'), it.get('vod_id', '')),
        })
    return {'list': out}


# ---------- 网页预览 ----------

_PREVIEW_CSS = """
:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;background:#111;color:#e6e6e6;font:14px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;background:#181818;padding:10px 12px;border-bottom:1px solid #262626;z-index:2}
h1{margin:0 0 8px;font-size:16px;font-weight:600}h1 small{color:#888;font-weight:400;margin-left:8px}
nav.top,nav.cats{display:flex;gap:6px;overflow:auto;padding-bottom:2px}
nav.cats{margin-top:6px}
nav.top a,nav.cats a,nav.top a:visited,nav.cats a:visited{flex:0 0 auto;padding:5px 12px;border-radius:999px;background:#222;color:#bbb;text-decoration:none;font-size:13px}
nav.top a.on,nav.cats a.on{background:#2b6cb0;color:#fff}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(108px,1fr));gap:10px;padding:12px}
.c{text-decoration:none;color:inherit}
.c img{width:100%;aspect-ratio:2/3;object-fit:cover;border-radius:6px;background:#222;display:block}
.m b{display:block;font-size:13px;margin-top:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.m span,.m em{display:block;font-size:11px;color:#8a8a8a;font-style:normal;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
footer{padding:16px 12px 40px;color:#666;font-size:12px}
"""


def preview_html(group_name, g, cat, items, nsrc):
    esc = html.escape
    title = '成人资源' if group_name == 'adult' else '影视资源'
    cards = ''.join(
        '<a class="c" href="%s" target="_blank" rel="noreferrer">'
        '<img loading="lazy" src="%s" alt="">'
        '<div class="m"><b>%s</b><span>%s %s</span><em>%s</em></div></a>' % (
            esc(str(x.get('vod_pic') or '')), esc(str(x.get('vod_pic') or '')),
            esc(str(x.get('vod_name') or '')),
            esc(str(x.get('type_name') or '')), esc(str(x.get('vod_remarks') or '')),
            esc(str(x.get('_src') or ''))) for x in items)
    top = ''.join('<a class="%s" href="/preview?g=%s">%s</a>' % (
        'on' if k == group_name else '', k, n) for k, n in
        (('other', '影视资源'), ('adult', '成人资源')))
    names = ['全部'] + [b.get('name') for b in (g.get('buckets') or [])]
    cats = ''.join('<a class="%s" href="/preview?g=%s&t=%s">%s</a>' % (
        'on' if n == cat else '', group_name,
        urllib.parse.quote(str(n)), esc(str(n))) for n in names)
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s · 聚合预览</title><style>%s</style></head><body>'
            '<header><h1>%s <small>%s 个源聚合 · 第 1 页 %s 条</small></h1>'
            '<nav class="top">%s</nav><nav class="cats">%s</nav></header>'
            '<div class="grid">%s</div>'
            '<footer>这是本机聚合预览。FongMi 里填 <code>%s</code>。</footer>'
            '</body></html>') % (
        esc(title), _PREVIEW_CSS, esc(title), nsrc, len(items), top, cats,
        cards or '<p style="padding:12px;color:#888">这一页没有拉到内容，换页或稍后再试。</p>',
        '/fongmi.json')
