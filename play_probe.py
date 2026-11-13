#!/usr/bin/env python3
"""play_probe.py —— 逐个源实测「详情 + 播放地址」是否真能用

之前 build_agg 只验证了列表接口，导致把「列表能出、详情空、播放地址 403/HTML/连不上」
的源一起聚合进来，点了播不了。这里对每个源取 N 条样本做端到端验证：

  列表 → detail → vod_play_url 首个地址 → HTTP 状态 + 前缀校验

判据：
  - 详情为空            → detail_ok=0
  - 播放地址 HTTP 非 2xx → play_ok=0
  - 返回 HTML/JSON 而非 m3u8/mp4 → play_ok=0（被反爬/落地页劫持）
  - 200 且是 #EXTM3U / 视频流 → play_ok=1

输出 play_probe.json：{name: {detail_ok, play_ok, n, rate, sample_err}}
"""
import json, os, re, subprocess, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
UA = 'Mozilla/5.0 (Linux; Android 12)'
SAMPLES = 4


def http_json(url, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'ignore'))


def fetch_text(url, timeout=12):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(4096).decode('utf-8', 'ignore')


def join(api, q):
    return api.split('?')[0] + '?' + q


def probe_src(site):
    name = str(site.get('name'))
    api, typ = str(site.get('api')), site.get('type')
    out = {'name': name, 'n': 0, 'detail_ok': 0, 'play_ok': 0, 'errs': {}}

    try:
        q = 'ac=videolist&pg=1' + ('&at=xml' if typ == 0 else '')
        body = urllib.request.urlopen(
            urllib.request.Request(join(api, q), headers={'User-Agent': UA}),
            timeout=15).read().decode('utf-8', 'ignore')
    except Exception as e:
        out['errs']['list'] = type(e).__name__
        return out

    ids = []
    if typ == 0 or body.lstrip().startswith('<'):
        ids = re.findall(r'<id>(\d+)</id>', body)[:SAMPLES]
    else:
        try:
            ids = [str(v.get('vod_id')) for v in (json.loads(body).get('list') or [])][:SAMPLES]
        except Exception as e:
            out['errs']['parse'] = type(e).__name__
            return out

    if not ids:
        out['errs']['list'] = 'empty'
        return out

    for vid in ids:
        out['n'] += 1
        try:
            q = f'ac=detail&ids={vid}' + ('&at=xml' if typ == 0 else '')
            raw = urllib.request.urlopen(
                urllib.request.Request(join(api, q), headers={'User-Agent': UA}),
                timeout=15).read().decode('utf-8', 'ignore')
            if typ == 0 or raw.lstrip().startswith('<'):
                m = re.search(r'<dd flag="[^"]*"><!\[CDATA\[(.*?)\]\]></dd>', raw, re.S)
                play = m.group(1) if m else ''
            else:
                lst = json.loads(raw).get('list') or []
                play = str(lst[0].get('vod_play_url') or '') if lst else ''
            if not play:
                out['errs']['detail'] = out['errs'].get('detail', 0) + 1
                continue
            out['detail_ok'] += 1
            first = play.split('#')[0].split('$')[-1].strip()
            if not first.startswith('http'):
                out['errs']['play_url'] = out['errs'].get('play_url', 0) + 1
                continue
            head = fetch_text(first)
            if head.lstrip().startswith('#EXTM3U') or head.lstrip()[:4] in ('\x00\x00\x00\x18', 'ftyp'):
                out['play_ok'] += 1
            elif head.lstrip().startswith('<'):
                out['errs']['html'] = out['errs'].get('html', 0) + 1
            else:
                out['errs']['not_m3u8'] = out['errs'].get('not_m3u8', 0) + 1
        except Exception as e:
            out['errs'][type(e).__name__] = out['errs'].get(type(e).__name__, 0) + 1

    out['rate'] = round(out['play_ok'] / out['n'], 2) if out['n'] else 0
    return out


def main():
    kinds = json.load(open(os.path.join(BASE, 'kinds2.json')))
    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(probe_src, kinds))
    rows.sort(key=lambda r: (-r.get('rate', 0), -r.get('play_ok', 0)))
    json.dump(rows, open(os.path.join(BASE, 'play_probe.json'), 'w'), ensure_ascii=False, indent=1)

    ok = [r for r in rows if r.get('play_ok', 0) > 0]
    print(f'可播源 {len(ok)}/{len(rows)}')
    for r in rows:
        print(f"  {r.get('rate', 0):<5} play={r.get('play_ok')}/{r.get('n')} detail={r.get('detail_ok')} "
              f"{r['name'][:16]:<18} {r.get('errs') or ''}")


if __name__ == '__main__':
    main()
