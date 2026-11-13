"""最小闭环验证：解析 VodConfig -> 测活 type 0/1 站点 -> 输出可用 vod.json
只做可行性验证，不是完整实现。"""
import json, time, ssl, urllib.request, concurrent.futures as cf, sys

ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
UA = {'User-Agent': 'okhttp/3.15'}

def load(path):
    d = json.load(open(path))
    sites = d.get('sites') or []
    # 归一化：type 可能是字符串
    for s in sites:
        try: s['type'] = int(s.get('type', 0))
        except (TypeError, ValueError): s['type'] = -1
    return d, sites

def probe_site(s, timeout=8):
    """type 0/1/4 纯 HTTP 测活：?ac=list，校验结构"""
    api = s.get('api') or ''
    if not api.startswith('http'):
        return (s, 'SKIP', '非 HTTP 端点')
    url = api + ('&' if '?' in api else '?') + 'ac=list'
    t = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={**UA, **(s.get('header') or {})}),
                                   timeout=timeout, context=ctx)
        body = r.read(200000)
        ms = round((time.time() - t) * 1000)
        text = body.decode('utf-8', 'ignore').strip()
        if text.startswith('{'):
            j = json.loads(text)
            n = len(j.get('class') or [])
            pc = j.get('pagecount') or j.get('total') or 0
            if n == 0 and not pc:
                return (s, 'DEAD', f'200 但无 class/pagecount')
            return (s, 'OK', f'{ms}ms classes={n} pages={pc}')
        if text.startswith('<?xml') or '<rss' in text[:200]:
            import re
            n = len(re.findall(r'<ty\b', text))
            return (s, 'OK', f'{ms}ms xml ty={n}')
        return (s, 'DEAD', f'200 但非 JSON/XML: {text[:30]}')
    except Exception as e:
        return (s, 'DEAD', f'{type(e).__name__}: {str(e)[:40]}')

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else '/tmp/t1.json'
    d, sites = load(src)
    print(f"源文件: {src}")
    print(f"站点总数 {len(sites)}，直播源 {len(d.get('lives') or [])} 个，解析器 {len(d.get('parses') or [])} 个")

    http_sites = [s for s in sites if s['type'] in (0, 1, 4)]
    spider_sites = [s for s in sites if s['type'] == 3]
    print(f"→ type 0/1/4（可自动测）: {len(http_sites)} 个")
    print(f"→ type 3（需 spider 运行时）: {len(spider_sites)} 个")
    print()

    print("== 测活 type 0/1/4 ==")
    results = []
    with cf.ThreadPoolExecutor(4) as ex:
        for s, status, detail in ex.map(probe_site, http_sites):
            results.append((s, status, detail))
            print(f"  [{status:4}] {s.get('name','')[:24]:26} {detail}")

    alive = [s for s, st, _ in results if st == 'OK']
    print(f"\n通过 {len(alive)}/{len(http_sites)}")

    # 输出：只保留通过的 HTTP 站点 + 原样保留 lives/parses/spider（lives 未测）
    out = {k: v for k, v in d.items() if k in ('spider', 'lives', 'parses', 'flags', 'doh', 'rules', 'headers', 'logo', 'wallpaper')}
    out['sites'] = alive
    path = '/app/working/fongmi-agg/prototype/sample-vod.json'
    json.dump(out, open(path, 'w'), ensure_ascii=False, indent=1)
    print(f"\n已输出 {path}（{len(alive)} 站点 / {len(out.get('lives') or [])} 直播源）")

    # 结构合规性自检
    assert isinstance(out['sites'], list) and all('key' in s and 'api' in s and 'name' in s for s in out['sites'])
    print("结构自检: sites 每项都有 key/api/name ✅")

if __name__ == '__main__':
    main()
