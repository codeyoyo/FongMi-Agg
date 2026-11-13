#!/usr/bin/env python3
"""deploy_pages.py —— 用 Cloudflare Pages Direct Upload 部署 + _worker.js 参数路由

用法：
  CLOUDFLARE_API_TOKEN=xxx python3 deploy_pages.py [项目名]

依赖：dist2/ 与 deploy/_worker.js
"""
import json, os, sys, urllib.request, uuid

TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN') or open(
    '/app/working/instabox-keepalive/.cf_token').read().strip()
ACCT = os.environ.get('CLOUDFLARE_ACCOUNT_ID', 'fcffd8e2ea9a87b44fa8ba5e6f5d485c')
PROJ = sys.argv[1] if len(sys.argv) > 1 else 'fongmi-sub'
BASE = os.path.dirname(os.path.abspath(__file__))
API = 'https://api.cloudflare.com/client/v4'


def req(method, path, data=None, ctype='application/json'):
    url = API + path
    body = None
    if data is not None:
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
    r = urllib.request.Request(url, data=body, method=method,
                               headers={'Authorization': f'Bearer {TOKEN}',
                                        'Content-Type': ctype})
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


def ensure_project():
    r = req('GET', f'/accounts/{ACCT}/pages/projects/{PROJ}')
    if r.get('success'):
        print(f'项目已存在: {PROJ}')
        return r['result']
    r = req('POST', f'/accounts/{ACCT}/pages/projects',
            {'name': PROJ, 'production_branch': 'main'})
    if not r.get('success'):
        print('创建项目失败:', r.get('errors'))
        sys.exit(1)
    print(f'已创建项目: {PROJ} → {r["result"].get("subdomain")}')
    return r['result']


def collect():
    """返回 [(相对路径, bytes)]"""
    out = []
    w = os.path.join(BASE, 'deploy', '_worker.js')
    out.append(('_worker.js', open(w, 'rb').read()))
    for root in ('dist2',):
        for dirpath, _, files in os.walk(os.path.join(BASE, root)):
            for f in files:
                p = os.path.join(dirpath, f)
                rel = os.path.relpath(p, os.path.join(BASE, root))
                out.append((rel, open(p, 'rb').read()))
    return out


def deploy(files):
    """multipart 上传（需 manifest 字段：路径 → hash/size）"""
    import hashlib
    boundary = '----cf' + uuid.uuid4().hex
    manifest = {'/' + name.lstrip('/'): {'hash': hashlib.sha256(content).hexdigest(),
                                         'size': len(content)}
                for name, content in files}
    parts = [
        (f'--{boundary}\r\nContent-Disposition: form-data; name="manifest"\r\n'
         f'Content-Type: application/json\r\n\r\n').encode()
        + json.dumps(manifest).encode() + b'\r\n'
    ]
    for name, content in files:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name.lstrip("/")}"; '
            f'filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
            + content + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    body = b''.join(parts)

    url = f'{API}/accounts/{ACCT}/pages/projects/{PROJ}/deployments'
    r = urllib.request.Request(url, data=body, method='POST', headers={
        'Authorization': f'Bearer {TOKEN}',
        'Content-Type': f'multipart/form-data; boundary={boundary}',
    })
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


if __name__ == '__main__':
    proj = ensure_project()
    files = collect()
    total = sum(len(c) for _, c in files)
    print(f'待上传 {len(files)} 个文件，合计 {total/1024:.0f} KB')
    r = deploy(files)
    if not r.get('success'):
        print('部署失败:', json.dumps(r.get('errors'), ensure_ascii=False)[:800])
        sys.exit(1)
    res = r['result']
    print('\n部署成功')
    print('  URL:', res.get('url'))
    print('  状态:', res.get('latest_stage', {}).get('status'))
    print('\n两个入口:')
    print(f'  https://{PROJ}.pages.dev/fongmi.json')
    print(f'  https://{PROJ}.pages.dev/fongmi.json?mode=full')
