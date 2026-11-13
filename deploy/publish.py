#!/usr/bin/env python3
"""publish.py —— 把 dist/ 发布到 Cloudflare Pages（Direct Upload）

用法：
  export CF_API_TOKEN=xxx CF_ACCOUNT_ID=yyy
  python3 publish.py [--project fongmi] [--dir dist]

所需 token 权限：Account → Cloudflare Pages → Edit
"""
import argparse, hashlib, json, mimetypes, os, sys, urllib.error, urllib.request
import uuid

API = 'https://api.cloudflare.com/client/v4'


def call(method, path, token, body=None, ctype='application/json', raw=None):
    url = API + path
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Authorization', f'Bearer {token}')
    if data is not None:
        req.add_header('Content-Type', ctype)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def ensure_project(token, acct, name):
    r = call('GET', f'/accounts/{acct}/pages/projects/{name}', token)
    if r.get('success'):
        return r['result']
    r = call('POST', f'/accounts/{acct}/pages/projects', token,
             {'name': name, 'production_branch': 'main'})
    if not r.get('success'):
        print('创建项目失败:', json.dumps(r.get('errors'), ensure_ascii=False))
        sys.exit(1)
    return r['result']


def deploy(token, acct, name, directory):
    files, manifest = [], {}
    for root, _, names in os.walk(directory):
        for fn in names:
            full = os.path.join(root, fn)
            rel = '/' + os.path.relpath(full, directory).replace(os.sep, '/')
            blob = open(full, 'rb').read()
            manifest[rel] = {'hash': hashlib.sha256(blob).hexdigest(), 'size': len(blob)}
            files.append((rel, blob))

    boundary = '----cf' + uuid.uuid4().hex
    parts = []
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="manifest"\r\n'
                 f'Content-Type: application/json\r\n\r\n{json.dumps(manifest)}\r\n'.encode())
    for rel, blob in files:
        ctype = mimetypes.guess_type(rel)[0] or 'application/octet-stream'
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{rel}"; '
                     f'filename="{os.path.basename(rel)}"\r\nContent-Type: {ctype}\r\n\r\n'.encode())
        parts.append(blob)
        parts.append(b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    body = b''.join(parts)

    r = call('POST', f'/accounts/{acct}/pages/projects/{name}/deployments', token,
             raw=body, ctype=f'multipart/form-data; boundary={boundary}')
    if not r.get('success'):
        print('部署失败:', json.dumps(r.get('errors'), ensure_ascii=False))
        return None
    return r['result']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--project', default='fongmi')
    ap.add_argument('--dir', default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'dist'))
    args = ap.parse_args()

    token = os.environ.get('CF_API_TOKEN') or ''
    acct = os.environ.get('CF_ACCOUNT_ID') or ''
    if not token or not acct:
        print('缺环境变量：CF_API_TOKEN / CF_ACCOUNT_ID')
        sys.exit(2)

    print(f'项目 {args.project}')
    proj = ensure_project(token, acct, args.project)
    print(f'  subdomain: {proj.get("subdomain")}')

    res = deploy(token, acct, args.project, args.dir)
    if not res:
        sys.exit(1)

    url = res.get('url')
    print(f'部署成功: {url}')
    print(f'  环境: {res.get("environment")}')
    aliases = res.get('aliases') or []
    if aliases:
        print(f'  别名: {", ".join(aliases)}')
        for a in aliases:
            if '.pages.dev' in a:
                print(f'\n订阅地址: https://{a}/fongmi.json')
                print(f'直播地址: https://{a}/live.m3u')
                break


if __name__ == '__main__':
    main()
