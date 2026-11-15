#!/usr/bin/env python3
"""fongmi-admin —— fongmi-agg 的 Web 管理台 + 本机订阅服务

管理台：看状态、编辑源/分类/产物、一键触发流水线。
订阅：/fongmi.json、/movie.json 等静态产物 + /movie、/adult 聚合接口，
      无需 Cloudflare；返回配置时按请求地址改写成当前 host。
      聚合实现见 app/aggregate.py（与 deploy/_worker.js 协议一致）。

启动：bin/admin.sh start（默认 0.0.0.0:8123；ADMIN_HOST=127.0.0.1 仅本机）
"""
import json, os, re, socket, subprocess, time, datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

try:
    from . import aggregate
except ImportError:                     # 兼容直接以脚本方式导入
    import aggregate

HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # fongmi-admin
# 默认仓库根：本仓库里 webui/ 的上一级就是根；容器里 admin 是独立副本，
# 上一级没有 pipeline/，回退到原来的 /app/working/fongmi-agg。
_DEFAULT_REPO = os.path.dirname(HOME)
if not os.path.isdir(os.path.join(_DEFAULT_REPO, 'pipeline')):
    _DEFAULT_REPO = '/app/working/fongmi-agg'
REPO = os.environ.get('FONGMI_REPO', _DEFAULT_REPO)
PIPELINE = os.path.join(REPO, 'pipeline', 'run_step.py')
RUNS = os.path.join(REPO, 'state', 'runs')
DIST2 = os.path.join(REPO, 'dist2')
DATA = os.path.join(HOME, 'data')
PUBLIC = os.environ.get('FONGMI_PUBLIC', 'https://fm.le138.de5.net')
PY = os.environ.get('FONGMI_PY', 'python3')

# 本机订阅入口：与 Cloudflare Worker 的 ?mode= 口径保持一致
LOCAL_MODE_MAP = {
    'two': 'two.json', 'movie': 'movie.json', 'full': 'full.json',
    'clean': 'clean.json', 'basic': 'basic.json',
    'other': 'other.json', 'adult': 'adult.json',
}
# 配置里聚合站写的是这个地址；本机返回时按请求 host 改写，同一份 dist2 两处都能用
PUBLIC_BASES = []
for _b in (PUBLIC, os.environ.get('FONGMI_AGG_BASE', ''),
           'https://fm.le138.de5.net', 'http://fm.le138.de5.net'):
    if _b:
        _b = _b.rstrip('/')
        if _b not in PUBLIC_BASES:
            PUBLIC_BASES.append(_b)

os.makedirs(DATA, exist_ok=True)
app = FastAPI(title='fongmi-admin', version='0.1.0-p0')


# ---------- 工具 ----------
def jload(path, default=None):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return default


def run_dirs():
    if not os.path.isdir(RUNS):
        return []
    return sorted((d for d in os.listdir(RUNS) if os.path.isdir(os.path.join(RUNS, d))), reverse=True)


def run_state(run_id):
    return jload(os.path.join(RUNS, run_id, 'run.json'), {'run_id': run_id, 'status': 'unknown'})


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


_probe_cache = {'ts': 0, 'data': None}


def probe_public(ttl=90):
    """探活线上四个入口（带 90s 缓存，避免每次刷页面都打网络）"""
    if time.time() - _probe_cache['ts'] < ttl and _probe_cache['data']:
        return _probe_cache['data']
    out = {}
    for name in ('fongmi.json', 'clean.json', 'full.json', 'basic.json', 'multi.json'):
        t0 = time.time()
        body = aggregate.fetch_text(PUBLIC.rstrip('/') + '/' + name, 12)
        if body is None:
            code, size, n = 0, 0, None
        else:
            code, size = 200, len(body.encode('utf-8', 'ignore'))
            try:
                d = json.loads(body)
                n = len(d.get('urls') or []) if 'urls' in d else len(d.get('sites') or [])
            except Exception:
                n = None
        out[name] = {'code': code, 'bytes': size, 'count': n,
                     'ms': int((time.time() - t0) * 1000)}
    _probe_cache.update(ts=time.time(), data=out)
    return out


# ---------- 认证：本机免；公网走 HTTP Basic（浏览器弹一次框）或 Bearer ----------
import base64
PASSFILE = os.path.join(HOME, 'run', '.password')
ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')


def _expected_pass():
    try:
        with open(PASSFILE, encoding='utf-8') as fh:
            v = fh.read().strip()
            if v:
                return v
    except Exception:
        pass
    return os.environ.get('ADMIN_PASS', '')


def _basic_ok(header):
    if not header or not header.lower().startswith('basic '):
        return False
    try:
        raw = base64.b64decode(header.split(' ', 1)[1]).decode('utf-8', 'ignore')
        u, _, pw = raw.partition(':')
    except Exception:
        return False
    exp = _expected_pass()
    if not exp:
        return False
    return u == ADMIN_USER and pw == exp


def _request_origin(request):
    proto = (request.headers.get('x-forwarded-proto') or request.url.scheme or 'http').split(',')[0].strip()
    host = (request.headers.get('x-forwarded-host') or request.headers.get('host')
            or request.url.netloc).split(',')[0].strip()
    return '%s://%s' % (proto, host)


def _rewrite_base(obj, origin):
    """把配置里的 Cloudflare 聚合地址换成本机访问地址；同一份 dist2 两处通用"""
    if isinstance(obj, str):
        for b in PUBLIC_BASES:
            if obj == b or obj.startswith(b + '/'):
                return origin + obj[len(b):]
        return obj
    if isinstance(obj, list):
        return [_rewrite_base(x, origin) for x in obj]
    if isinstance(obj, dict):
        return {k: _rewrite_base(v, origin) for k, v in obj.items()}
    return obj


def _artifact_json(fname, request):
    if (not fname or os.path.basename(fname) != fname
            or fname.startswith('.') or '..' in fname or not fname.endswith('.json')):
        raise HTTPException(400, '非法产物文件名')
    p = os.path.join(DIST2, fname)
    if not os.path.isfile(p) and fname == 'artifacts.json':
        p = os.path.join(REPO, 'config', 'artifacts.json')
    if not os.path.isfile(p):
        raise HTTPException(404, '没有这个产物：' + fname)
    try:
        with open(p, encoding='utf-8') as fh:
            data = json.load(fh)
    except Exception:
        raise HTTPException(422, '产物不是合法 JSON')
    return JSONResponse(_rewrite_base(data, _request_origin(request)),
                        headers={'cache-control': 'no-cache, must-revalidate',
                                 'access-control-allow-origin': '*'})


def _lan_ips():
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith('127.') or ip.startswith('169.254.') or ip in out:
                continue
            out.append(ip)
    except Exception:
        pass
    if not out:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            out.append(s.getsockname()[0])
            s.close()
        except Exception:
            pass
    return out


@app.middleware('http')
async def guard(request: Request, call_next):
    path = request.url.path
    if path == '/api/health':
        return await call_next(request)
    # 订阅/聚合路径供电视端直接访问，不走后台登录；后台 / 与 /api/* 仍受保护
    if path in ('/fongmi.json', '/movie', '/other', '/adult', '/preview') or (
            path.endswith('.json') and not path.startswith('/api/')):
        return await call_next(request)
    client = request.client.host if request.client else ''
    # 走隧道进来的请求一定带 CF/XFF 头：即便源地址看着是回环也强制认证，
    # 否则任何人伪造 X-Forwarded-For 就能冒充本机绕过登录
    tunneled = any(request.headers.get(h) for h in ('cf-connecting-ip', 'x-forwarded-for'))
    if client in ('127.0.0.1', '::1') and not tunneled:
        return await call_next(request)
    auth = request.headers.get('authorization', '')
    token = os.environ.get('ADMIN_TOKEN', '')
    if _basic_ok(auth) or (token and auth == f'Bearer {token}'):
        return await call_next(request)
    return JSONResponse({'error': 'unauthorized'}, status_code=401,
                        headers={'WWW-Authenticate': 'Basic realm="FongMI Admin", charset="UTF-8"'})


# ---------- API ----------
@app.get('/api/health')
def health():
    return {'ok': True, 'repo': REPO, 'ts': datetime.datetime.now().isoformat(timespec='seconds')}


@app.get('/api/dashboard')
def dashboard(request: Request):
    def cnt(f, key='sites'):
        d = jload(os.path.join(DIST2, f), {})
        return len(d.get(key) or [])
    defs = jload(ART_FILE, {'artifacts': []})
    art_files = [a.get('file') or (a.get('id') + '.json')
                 for a in (defs.get('artifacts') or []) if a.get('enabled', True)]
    if not art_files:
        art_files = ['two.json']
    # 直播信息从任一含 lives 的产物里取（产物文件名可自定义，不再写死 clean.json）
    lives = []
    for f in art_files + ['two.json']:
        d = jload(os.path.join(DIST2, f), {})
        if d.get('lives'):
            lives = d['lives']
            break
    groups = (lives[0].get('groups') or []) if lives else []
    last = run_state(run_dirs()[0]) if run_dirs() else None
    agg = jload(os.path.join(DIST2, 'agg_srcs.json'), {})
    cats = [(b.get('name'), len(b.get('srcs') or [])) for b in (agg.get('other', {}).get('buckets') or [])]
    mtimes = {}
    for f in art_files + ['two.json', 'multi.json']:
        p = os.path.join(DIST2, f)
        mtimes[f] = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%m-%d %H:%M') if os.path.exists(p) else None
    port = int(os.environ.get('ADMIN_PORT', '8123') or 8123)
    origin = _request_origin(request)
    urls = [origin + '/fongmi.json']
    for ip in ['127.0.0.1'] + [ip for ip in _lan_ips() if ip != '127.0.0.1']:
        u = 'http://%s:%s/fongmi.json' % (ip, port)
        if u not in urls:
            urls.append(u)
    return {
        'artifacts': {f: cnt(f) for f in art_files},
        'multi': cnt('multi.json', 'urls'),
        'lives': {'groups': len(groups), 'channels': sum(len(g.get('channel') or []) for g in groups)},
        'categories': cats,
        'built_at': mtimes,
        'last_run': last,
        'public': probe_public(),
        'public_base': PUBLIC,
        'local_urls': urls,
    }


@app.get('/api/sources')
def sources():
    cfg = jload(os.path.join(REPO, 'config', 'manual_sources.json'), {})
    intl = jload(os.path.join(REPO, 'config', 'intl_channels.json'), [])
    def norm(lst, kind):
        return [{'kind': kind, 'name': x.get('name'), 'url': x.get('url'),
                 'src': x.get('src') or x.get('cc') or '', 'enabled': True} for x in lst]
    return {'vod': norm(cfg.get('vod') or [], 'vod'),
            'live': norm(cfg.get('live') or [], 'live'),
            'intl': norm(intl if isinstance(intl, list) else [], 'intl'),
            'counts': {'vod': len(cfg.get('vod') or []), 'live': len(cfg.get('live') or []),
                       'intl': len(intl if isinstance(intl, list) else [])}}


# ---------- P1：源编辑 ----------
import shutil, re
MANUAL = os.environ.get('FONGMI_MANUAL') or os.path.join(REPO, 'config', 'manual_sources.json')
INTL = os.path.join(REPO, 'config', 'intl_channels.json')


def _manual_path():
    p = Path(MANUAL)
    if not p.is_absolute():
        p = Path(REPO, p)
    p = p.resolve()
    if p.parent != Path(REPO, 'config').resolve() or p.suffix != '.json':
        raise HTTPException(500, 'MANUAL 路径非法')
    return p


def _read_manual():
    return jload(str(_manual_path()), {'vod': [], 'live': [], 'intl': []})


def _write_manual(cfg, reason):
    """回写 JSON + 尽力 git commit（失败不影响保存）"""
    _manual_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding='utf-8')
    try:
        subprocess.run(['git', 'add', 'config/manual_sources.json'], cwd=REPO,
                       capture_output=True, timeout=20)
        subprocess.run(['git', '-c', 'user.name=fongmi-admin', '-c', 'user.email=admin@local',
                        'commit', '-q', '-m', f'ui: {reason}'], cwd=REPO,
                       capture_output=True, timeout=20)
    except Exception:
        pass
    return {'ok': True}


@app.post('/api/sources/preview')
async def preview_sources(request: Request):
    """预检：只解析、不落盘。返回每条识别到多少站 / 错误原因"""
    body = await request.json()
    kind = body.get('kind', 'vod')
    urls = [u.strip() for u in str(body.get('urls', '')).splitlines() if u.strip()]
    if not urls:
        raise HTTPException(400, '没有地址')
    if len(urls) > 60:
        raise HTTPException(400, '一次最多 60 条')
    out = []
    for u in urls:
        if kind != 'vod':
            out.append({'url': u, 'ok': True, 'kind': kind, 'sites': None,
                        'note': '直播/境外源不预解析，写入后由合并步骤处理'})
            continue
        try:
            code = f"""
import sys, json
sys.path.insert(0, {os.path.join(REPO, 'pipeline')!r})
from load_manual import parse_config
sites, js, errs = parse_config({u!r}, 'preview')
print(json.dumps({{'sites': len(sites), 'js': len(js), 'errs': errs[:2],
                  'types': {{t: sum(1 for x in sites if x.get('type')==t) for t in (0,1,4)}}}}))
"""
            r = subprocess.run([PY, '-c', code], cwd=REPO, capture_output=True,
                               text=True, timeout=90)
            if r.returncode != 0:
                out.append({'url': u, 'ok': False, 'sites': 0, 'error': (r.stderr or '')[-200:]})
            else:
                d = json.loads(r.stdout.strip().splitlines()[-1])
                ok = (int(d.get('sites') or 0) + int(d.get('js') or 0)) > 0
                if not ok and not d.get('errs'):
                    d['errs'] = ['解析成功但没有可用站点']
                out.append({'url': u, 'ok': ok, **d})
        except subprocess.TimeoutExpired:
            out.append({'url': u, 'ok': False, 'sites': 0, 'error': '超时 90s'})
        except Exception as e:
            out.append({'url': u, 'ok': False, 'sites': 0, 'error': str(e)[:200]})
    return {'items': out,
            'summary': {'total': len(out), 'ok': sum(1 for x in out if x['ok']),
                        'sites': sum(int(x.get('sites') or 0) for x in out)}}


@app.post('/api/sources/add')
async def add_sources(request: Request):
    body = await request.json()
    kind = body.get('kind', 'vod')
    items = body.get('items') or []
    if kind not in ('vod', 'live'):
        raise HTTPException(400, '只支持 vod / live（境外走 intl_channels.json，另行处理）')
    cfg = _read_manual()
    cfg.setdefault(kind, [])
    have = {(x.get('url') or '').rstrip('/') for x in cfg[kind]}
    added, dup = [], []
    for it in items:
        u = (it.get('url') or '').strip()
        if not u:
            continue
        if u.rstrip('/') in have:
            dup.append(u); continue
        cfg[kind].append({'name': (it.get('name') or u.split('/')[-1])[:40],
                          'url': u, 'src': 'gui'})
        have.add(u.rstrip('/')); added.append(u)
    if added:
        _write_manual(cfg, f'+{len(added)} {kind} 源（GUI）')
    return {'added': len(added), 'duplicate': len(dup), 'total': len(cfg[kind])}


@app.post('/api/sources/delete')
async def delete_source(request: Request):
    body = await request.json()
    kind = body.get('kind', 'vod')
    url = (body.get('url') or '').strip()
    cfg = _read_manual()
    lst = cfg.get(kind) or []
    left = [x for x in lst if (x.get('url') or '').strip() != url]
    if len(left) == len(lst):
        raise HTTPException(404, '没找到这条源')
    cfg[kind] = left
    _write_manual(cfg, f'-1 {kind} 源（GUI）')
    return {'deleted': 1, 'total': len(left)}


@app.get('/api/runs')
def runs():
    items = []
    for r in run_dirs()[:20]:
        st = run_state(r)
        items.append({'run_id': r, 'status': st.get('status'), 'started': st.get('started'),
                      'finished': st.get('finished'), 'duration_ms': st.get('duration_ms'),
                      'steps': [s.get('step') for s in (st.get('steps') or [])],
                      'counters': st.get('counters') or {}})
    return {'runs': items}


@app.get('/api/runs/{run_id}')
def run_detail(run_id: str):
    if '/' in run_id or '..' in run_id:
        raise HTTPException(400)
    st = jload(os.path.join(RUNS, run_id, 'run.json'))
    if st is None:
        raise HTTPException(404)
    steps = []
    for f in sorted(os.listdir(os.path.join(RUNS, run_id))):
        if f.endswith('.json') and f != 'run.json':
            j = jload(os.path.join(RUNS, run_id, f), {})
            steps.append(j)
    return {'run': st, 'steps': steps}


@app.get('/api/runs/{run_id}/log/{step}')
def run_log(run_id: str, step: str, tail: int = 20000):
    if '/' in run_id or '..' in run_id or '/' in step or '..' in step:
        raise HTTPException(400)
    p = os.path.join(RUNS, run_id, step + '.log')
    if not os.path.exists(p):
        return {'log': ''}
    with open(p, encoding='utf-8', errors='ignore') as fh:
        data = fh.read()
    return {'log': data[-tail:]}


@app.post('/api/runs')
async def start_run(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    deploy = bool(body.get('deploy'))
    skip_probe = bool(body.get('skip_probe'))
    if skip_probe:
        # 只生成：复用上次测活结果直接重建产物，不再拉源/测活
        need = [os.path.join(REPO, 'state', 'ok_api_final.json')]
        pool = os.path.join(REPO, 'state', 'sites_verified_pool.json')
        missing = [p for p in need if not os.path.isfile(p)]
        if not os.path.isfile(pool) and not all(
                os.path.isfile(os.path.join(REPO, 'state', f))
                for f in ('sites_clean.json', 'verify_result.json')):
            missing.append(pool)
        if missing:
            raise HTTPException(400, '没有可复用的测活结果：' + '、'.join(
                os.path.relpath(p, REPO) for p in missing) + '。先跑一次「一键全流程」。')
        steps = ['07_build'] + (['08_deploy'] if deploy else [])
    else:
        steps = body.get('steps') or ['01_fetch', '02_probe', '03_dedupe', '04_classify',
                                      '05_verify', '06_search', '07_build', '08_deploy']
        if not deploy:
            steps = [s for s in steps if s != '08_deploy']

    # 并发保护：已有 running 且进程还在，拒绝
    for r in run_dirs()[:3]:
        st = run_state(r)
        if st.get('status') == 'running' and pid_alive(st.get('pid') or 0):
            raise HTTPException(409, f'已有运行中的任务 {r}')

    run_id = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    if not re.fullmatch(r'\d{8}-\d{6}', run_id):
        raise HTTPException(500, 'run_id 生成异常')
    rd = Path(RUNS, run_id)
    rd.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env['STEP08_DEPLOY'] = '1' if deploy else '0'
    if skip_probe:
        env['STEP07_MULTI'] = '0'   # 只生成：跳过慢的 75 个上游配置探测
    cmd = [PY, PIPELINE, '--run-id', run_id, '--steps', ','.join(steps)]
    p = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    st = {'run_id': run_id, 'status': 'running', 'pid': p.pid,
          'started': datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S'),
          'steps': [{'step': s, 'rc': None} for s in steps], 'counters': {},
          'requested': {'deploy': deploy, 'skip_probe': skip_probe, 'steps': steps}}
    Path(rd, 'run.json').write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding='utf-8')
    return {'run_id': run_id, 'pid': p.pid, 'steps': steps, 'deploy': deploy}


@app.get('/api/artifacts')
def artifacts():
    out = []
    if os.path.isdir(DIST2):
        for f in sorted(os.listdir(DIST2)):
            p = os.path.join(DIST2, f)
            if not os.path.isfile(p):
                continue
            item = {'file': f, 'bytes': os.path.getsize(p),
                    'mtime': datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%m-%d %H:%M')}
            if f.endswith('.json'):
                d = jload(p, {})
                if 'urls' in d:
                    item['count'] = len(d['urls']); item['kind'] = 'multi'
                elif 'sites' in d:
                    item['count'] = len(d['sites']); item['kind'] = 'config'
                elif isinstance(d, list):
                    item['count'] = len(d); item['kind'] = 'list'
            out.append(item)
    return {'files': out}


@app.get('/api/artifacts/{fname}/preview')
def artifact_preview(fname: str, n: int = 20):
    """产物前 N 项：只读 dist2 下的产物文件，不读目录外的东西"""
    if '/' in fname or '..' in fname or not fname.endswith('.json'):
        raise HTTPException(400, '只支持 dist2 下的 json 产物')
    path = os.path.join(DIST2, fname)
    if not os.path.isfile(path):
        raise HTTPException(404, '没有这个产物')
    d = jload(path, None)
    if d is None:
        raise HTTPException(422, '不是合法 JSON')
    n = max(1, min(int(n or 20), 100))
    items = []
    if isinstance(d, dict) and 'urls' in d:            # 多仓
        for u in (d.get('urls') or [])[:n]:
            items.append({'name': u.get('name'), 'url': u.get('url')})
        total = len(d.get('urls') or [])
    elif isinstance(d, dict) and 'sites' in d:          # tvbox 配置
        for x in (d.get('sites') or [])[:n]:
            items.append({'name': x.get('name'), 'url': x.get('api'),
                          'type': x.get('type'), 'total': x.get('_total')})
        total = len(d.get('sites') or [])
    elif isinstance(d, list):
        for x in d[:n]:
            items.append({'name': x.get('name'), 'url': x.get('api') or x.get('url'),
                          'type': x.get('type'), 'total': x.get('_total')})
        total = len(d)
    else:
        raise HTTPException(422, '不认识的结构')
    return {'file': fname, 'total': total, 'shown': len(items), 'items': items}


# ---------- 产物定义（可自定义） ----------
ART_FILE = os.path.join(REPO, 'config', 'artifacts.json')
VALID_POOLS = ('clean', 'full')
VALID_TYPES = ('list', 'agg_movie', 'agg_adult')


def _artifact_types(a):
    """产物类型数组。新格式 types；旧格式 type/group 自动兼容。"""
    t = a.get('types')
    if isinstance(t, list):
        return [x for x in t if x in VALID_TYPES]
    if a.get('type') == 'agg':
        return ['agg_adult' if (a.get('group') or 'movie') == 'adult' else 'agg_movie']
    return ['list']


GROUP_LABEL = {'other': '影视资源组', 'adult': '成人组'}
# 产物 group（聚合站数据源）→ 分类 tab 里的组key
ART_GROUP = {'movie': 'other', 'adult': 'adult'}


def _bucket_groups():
    """分类桶的唯一真相源 = 「分类」tab 保存的 config/categories.json。
    分类 tab 改桶名/加删桶后，产物定义里的勾选项直接跟着变。"""
    cfg = jload(CATEGORIES, {}) or {}
    out = []
    for key, spec in (cfg.get('groups') or {}).items():
        names = spec.get('order') or [b.get('name') for b in (spec.get('buckets') or [])]
        names = [n for n in names if n]
        if names:
            out.append({'key': key, 'label': GROUP_LABEL.get(key, key), 'buckets': names})
    return out


def _buckets_for(group_key):
    for g in _bucket_groups():
        if g['key'] == group_key:
            return g['buckets']
    return []


def _bucket_names():
    return _buckets_for('other')


@app.get('/api/artifact-defs')
def get_artifact_defs():
    cfg = jload(ART_FILE, {'artifacts': []})
    arts = []
    for a in (cfg.get('artifacts') or []):
        a = dict(a)
        a['types'] = _artifact_types(a)
        arts.append(a)
    return {'artifacts': arts, 'buckets': _bucket_names(),
            'groups': _bucket_groups(), 'pools': list(VALID_POOLS), 'types': list(VALID_TYPES),
            'note': 'types 可多选；pool/include_js/lives/buckets 仍保存在文件里继续生效'}


@app.post('/api/artifact-defs')
async def save_artifact_defs(request: Request):
    body = await request.json()
    arts = body.get('artifacts') or []
    errs = []
    files, ids = set(), set()
    for a in arts:
        i = a.get('id') or ''
        if not i or not i.replace('-', '').replace('_', '').isalnum():
            errs.append(f'产物 id「{i}」只能包含字母数字-_')
        if i in ids:
            errs.append(f'产物 id「{i}」重复')
        ids.add(i)
        f = a.get('file') or ''
        if not f.endswith('.json') or os.path.basename(f) != f:
            errs.append(f'产物「{i}」的文件名必须是纯文件名且 .json 结尾')
        if f in files:
            errs.append(f'文件名「{f}」重复')
        files.add(f)

        # types 多选：空数组视为“一个都没选”，不能再回退到旧 type/group
        types = _artifact_types(a)
        if not types:
            errs.append(f'产物「{i}」至少要选一种类型')
        a['types'] = types
        agg_types = [t for t in types if t.startswith('agg_')]
        if types == ['list']:
            a['type'] = 'list'
            a.pop('group', None)
        elif agg_types:
            a['type'] = 'agg'
            a['group'] = agg_types[0].split('_', 1)[1]

        # 界面已隐藏这些设置，但已有值必须保留；新建产物给默认值
        a.setdefault('pool', 'clean')
        if 'list' in types and a.get('pool') not in VALID_POOLS:
            errs.append(f'产物「{i}」的 pool 只能是 clean/full')
        a.setdefault('include_js', True)
        a.setdefault('lives', True)
        a.setdefault('buckets', 'all')
        a.setdefault('enabled', True)

        b = a.get('buckets')
        if b != 'all':
            if not isinstance(b, list):
                errs.append(f'产物「{i}」的 buckets 必须是 all 或分类数组')
            else:
                allowed = set()
                for g in _bucket_groups():
                    allowed.update(g['buckets'])
                unknown = [x for x in b if x not in allowed]
                if unknown:
                    errs.append(f'产物「{i}」含未知分类：{unknown}（分类以「分类」tab 为准）')
        if '..' in str(a.get('clip') or ''):
            errs.append(f'产物「{i}」的 clip 含非法路径')
    if errs:
        raise HTTPException(400, '；'.join(errs[:6]))
    payload = {'note': 'GUI 可编辑；类型可多选；改完重跑 07 生成生效', 'artifacts': arts}
    Path(ART_FILE).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    try:
        subprocess.run(['git', 'add', 'config/artifacts.json'], cwd=REPO, capture_output=True, timeout=20)
        subprocess.run(['git', '-c', 'user.name=fongmi-admin', '-c', 'user.email=admin@local',
                        'commit', '-q', '-m', 'ui: 更新产物定义'], cwd=REPO, capture_output=True, timeout=20)
    except Exception:
        pass
    return {'ok': True, 'count': len(arts), 'note': '已保存；重跑 07 生成后生效'}


# ---------- P2：产物快照 / 回滚 ----------
SNAPS = os.path.join(REPO, 'state', 'snapshots')


@app.get('/api/snapshots')
def list_snapshots():
    out = []
    if os.path.isdir(SNAPS):
        for sid in sorted(os.listdir(SNAPS), reverse=True)[:30]:
            meta = jload(os.path.join(SNAPS, sid, 'meta.json'))
            if not meta:
                continue
            out.append({'id': sid, 'created': meta.get('created'), 'run_id': meta.get('run_id'),
                        'files': meta.get('files') or {}})
    return {'snapshots': out}


@app.post('/api/snapshots/{sid}/restore')
def restore_snapshot(sid: str):
    if '/' in sid or '..' in sid:
        raise HTTPException(400)
    src = os.path.join(SNAPS, sid)
    meta = jload(os.path.join(src, 'meta.json'))
    if not meta:
        raise HTTPException(404, '没有这个快照')
    # 回滚前先给「现在这一版」留一份，避免回滚本身变成不可逆
    import shutil, hashlib
    pre = datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '-pre-restore'
    dst = os.path.join(SNAPS, pre)
    os.makedirs(dst, exist_ok=True)
    saved = {}
    for f in os.listdir(src):
        if not f.endswith('.json') or f == 'meta.json':
            continue
        cur = os.path.join(DIST2, f)
        if os.path.isfile(cur):
            shutil.copy2(cur, os.path.join(dst, f))
            saved[f] = {'bytes': os.path.getsize(cur)}
    Path(dst, 'meta.json').write_text(
        json.dumps({'id': pre, 'created': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'run_id': 'pre-restore', 'files': saved}, ensure_ascii=False, indent=1),
        encoding='utf-8')
    # 还原
    restored = []
    for f in (meta.get('files') or {}):
        s_path = os.path.join(src, f)
        if os.path.isfile(s_path):
            shutil.copy2(s_path, os.path.join(DIST2, f))
            restored.append(f)
    return {'ok': True, 'restored': restored, 'pre_restore': pre,
            'note': 'dist2 已还原；线上要真正生效还需点一次发布'}


# ---------- P2：分类编辑 ----------
CATEGORIES = os.path.join(REPO, 'config', 'categories.json')


def _check_categories(cfg):
    """返回 (errors, warnings)：正向关键词两两不得重叠，这是本项目串味的老病根"""
    errors, warnings = [], []
    groups = cfg.get('groups') or {}
    if 'other' not in groups:
        errors.append('缺少 other 组')
        return errors, warnings
    for g, spec in groups.items():
        bl = spec.get('buckets') or []
        order = spec.get('order') or []
        names = [b.get('name') for b in bl]
        for n in order:
            if n not in names:
                errors.append(f'{g}：order 里的「{n}」没有对应桶定义')
        if len(set(names)) != len(names):
            errors.append(f'{g}：桶名重复')
        pos = {}
        for b in bl:
            nm, kws = b.get('name'), [k for k in (b.get('kws') or []) if k]
            if not kws and nm != '其它':
                warnings.append(f'{g}：桶「{nm}」没有关键词，永远不会收到内容')
            for k in kws:
                pos.setdefault(k, []).append(nm)
            if len(set(kws)) != len(kws):
                warnings.append(f'{g}：桶「{nm}」关键词有重复项')
        for k, owners in pos.items():
            if len(set(owners)) > 1:
                errors.append('关键词「%s」同时属于：%s' % (k, '、'.join(sorted(set(owners)))))
        for b in bl:
            for x in (b.get('xkws') or []):
                if x and x in (b.get('kws') or []):
                    warnings.append(f'{g}：桶「{b.get("name")}」的排除词「{x}」同时是它自己的正向词')
    return errors, warnings


@app.get('/api/categories')
def get_categories():
    cfg = jload(CATEGORIES)
    if cfg is None:
        raise HTTPException(404, 'config/categories.json 不存在，先跑 python3 builders/build_agg.py --dump-categories')
    return cfg


@app.post('/api/categories/validate')
async def validate_categories(request: Request):
    cfg = await request.json()
    e, w = _check_categories(cfg)
    return {'ok': not e, 'errors': e, 'warnings': w}


@app.post('/api/categories')
async def save_categories(request: Request):
    cfg = await request.json()
    e, w = _check_categories(cfg)
    if e:
        raise HTTPException(400, '；'.join(e[:5]))
    shutil.copyfile(CATEGORIES, CATEGORIES + '.bak')
    Path(CATEGORIES).write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding='utf-8')
    try:
        subprocess.run(['git', 'add', 'config/categories.json'], cwd=REPO, capture_output=True, timeout=20)
        subprocess.run(['git', '-c', 'user.name=fongmi-admin', '-c', 'user.email=admin@local',
                        'commit', '-q', '-m', 'ui: 更新分类桶'], cwd=REPO, capture_output=True, timeout=20)
    except Exception:
        pass
    return {'ok': True, 'warnings': w, 'note': '配置已保存；下次 07_build 生效'}


# ---------- 本机订阅 / 聚合 ----------
# 同一份 dist2：/fongmi.json、/movie.json 等直接给 FongMi 订阅；
# /movie、/adult 是本机聚合接口，协议与 deploy/_worker.js 一致。
@app.get('/fongmi.json')
def local_fongmi(request: Request):
    mode = (request.query_params.get('mode') or 'two').lower()
    fname = LOCAL_MODE_MAP.get(mode)
    if not fname:
        return JSONResponse({'error': 'unknown mode', 'mode': mode}, status_code=404)
    return _artifact_json(fname, request)


@app.get('/{fname}.json')
def local_artifact(fname: str, request: Request):
    # 路由模板是 /{fname}.json，fname 拿到的是不带后缀的 movie
    return _artifact_json(fname + '.json', request)


def _agg(group_name, request):
    g = aggregate.load_group(group_name)
    if not g:
        return JSONResponse({'list': [], 'error': 'agg_srcs.json 缺失'}, status_code=500)
    g = aggregate.scope_by_artifact(g, request.query_params.get('m'))
    accept = request.headers.get('accept') or ''
    ac = (request.query_params.get('ac') or '').lower()
    wd = request.query_params.get('wd')
    if not ac and not wd and 'text/html' in accept:
        return RedirectResponse('/preview?g=' + group_name, status_code=302)
    ids = request.query_params.get('ids') or ''
    t = request.query_params.get('t')
    try:
        pg = max(1, int(request.query_params.get('pg') or 1))
    except (TypeError, ValueError):
        pg = 1
    if wd:
        body = aggregate.handle_search(g, wd, pg)
    elif ids:
        body = aggregate.handle_detail(g, ids)
    elif t:
        body = aggregate.handle_category(g, t, pg, bool(request.query_params.get('debug')))
    else:
        body = aggregate.handle_list(g)
    return JSONResponse(body, headers={'cache-control': 'public, max-age=300',
                                       'access-control-allow-origin': '*'})


@app.get('/movie')
@app.get('/other')
def agg_movie(request: Request):
    return _agg('other', request)


@app.get('/adult')
def agg_adult(request: Request):
    return _agg('adult', request)


@app.get('/preview')
def agg_preview(request: Request):
    group_name = 'adult' if request.query_params.get('g') == 'adult' else 'other'
    g = aggregate.load_group(group_name)
    if not g:
        return HTMLResponse('agg_srcs.json 缺失', status_code=500)
    cat = request.query_params.get('t') or '全部'
    body = aggregate.handle_category(g, cat, 1)
    srcs = aggregate.unique_srcs(g)
    items = []
    for x in (body.get('list') or []):
        try:
            idx = int(str(x.get('vod_id')).split('|')[0][1:])
        except Exception:
            idx = -1
        items.append({**x, '_src': srcs[idx].get('name') if 0 <= idx < len(srcs) else ''})
    return HTMLResponse(aggregate.preview_html(group_name, g, cat, items, len(srcs)),
                        headers={'cache-control': 'public, max-age=120'})


# ---------- 静态页 ----------
app.mount('/static', StaticFiles(directory=os.path.join(HOME, 'static')), name='static')


@app.get('/')
def index():
    return FileResponse(os.path.join(HOME, 'static', 'index.html'))
