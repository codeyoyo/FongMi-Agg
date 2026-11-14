#!/usr/bin/env python3
"""生成多仓订阅 multi.json。

FongMi 的「配置」页支持多仓（{"urls":[{name,url}]}）——加一条链接，
配置列表里就出现全部子配置，可逐个切换。这就是统一入口的对外形态。

只收录实测能拉到的配置：每个 URL 探测一次，200 且首字符是 { 或能解析出站点才算。
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pipeline'))
from load_manual import fetch, parse_config  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL = os.path.join(BASE, 'manual_sources.json')
OWN = 'https://fm.le138.de5.net/clean.json'


def main():
    cfg = json.load(open(MANUAL, encoding='utf-8'))
    urls = [{'name': '⭐ 本机优选（实测可播）', 'url': OWN}]
    bad = []
    for item in cfg.get('vod', []):
        name, url = item['name'], item['url']
        try:
            text = fetch(url).strip()
        except Exception as e:
            bad.append(f"{name}({type(e).__name__})")
            continue
        if not (text.startswith('{') or text.startswith('//') or ',' in text.splitlines()[0]):
            bad.append(f'{name}(非配置)')
            continue
        # 能解析出站点或多仓才算有效
        sites, jss, errs = parse_config(url, name)
        if not sites and errs:
            bad.append(f'{name}(空)')
            continue
        urls.append({'name': name, 'url': url})
        print(f'  ✓ {name:<18} {len(sites):>3} 站')

    out = os.path.join(BASE, 'dist', 'multi.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({'urls': urls}, open(out, 'w'), ensure_ascii=False, indent=1)
    print(f"\n多仓 {len(urls)} 条 → {out}")
    if bad:
        print('跳过:', ', '.join(bad))


if __name__ == '__main__':
    main()
