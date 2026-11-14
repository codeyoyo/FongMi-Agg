#!/usr/bin/env python3
"""fongmi-admin —— fongmi-agg 的 Web 管理台（P0）

只做三件事：看状态、编辑不了但能看源清单、一键触发流水线。
所有算法仍在 /app/working/fongmi-agg 的脚本里，这里只是编排器。

启动：bin/admin.sh start        （监听 127.0.0.1:8123）
"""
import json, os, subprocess, time, urllib.request, datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # fongmi-admin
REPO = os.environ.get('FONGMI_REPO', '/app/working/fongmi-agg')
PIPELINE = os.path.join(REPO, 'pipeline', 'run_step.py')
RUNS = os.path.join(REPO, 'state', 'runs')
DIST2 = os.path.join(REPO, 'dist2')
DATA = os.path.join(HOME, 'data')
PUBLIC = os.environ.get('FONGMI_PUBLIC', 'https://fm.le138.de5.net')
PY = os.environ.get('FONGMI_PY', 'python3')

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
        try:
            req = urllib.request.Request(f'{PUBLIC}/{name}',
                                         headers={'User-Agent': 'fongmi-admin/0.1'})
            with urllib.request.urlopen(req, timeout=12) as r:
                body = r.read(4000000)
            code, size = r.status, len(body)
            try:
                d = json.loads(body.decode('utf-8', 'ignore'))
                n = len(d.get('urls') or []) if 'urls' in d else len(d.get('sites') or [])
            except Exception:
                n = None
        except Exception as e:
            code, size, n = 0, 0, None
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


@app.middleware('http')
async def guard(request: Request, call_next):
    if request.url.path == '/api/health':
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
def dashboard():
    def cnt(f, key='sites'):
        d = jload(os.path.join(DIST2, f), {})
        return len(d.get(key) or [])
    clean = jload(os.path.join(DIST2, 'clean.json'), {})
    lives = clean.get('lives') or []
    groups = lives[0].get('groups') if lives else []
    last = run_state(run_dirs()[0]) if run_dirs() else None
    agg = jload(os.path.join(DIST2, 'agg_srcs.json'), {})
    cats = [(b.get('name'), len(b.get('srcs') or [])) for b in (agg.get('other', {}).get('buckets') or [])]
    mtimes = {}
    for f in ('clean.json', 'full.json', 'basic.json', 'multi.json', 'two.json'):
        p = os.path.join(DIST2, f)
        mtimes[f] = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%m-%d %H:%M') if os.path.exists(p) else None
    return {
        'artifacts': {'clean': cnt('clean.json'), 'full': cnt('full.json'),
                      'basic': cnt('basic.json'), 'multi': cnt('multi.json', 'urls'),
                      'two': cnt('two.json')},
        'lives': {'groups': len(groups), 'channels': sum(len(g.get('channel') or []) for g in groups)},
        'categories': cats,
        'built_at': mtimes,
        'last_run': last,
        'public': probe_public(),
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


def _read_manual():
    return jload(MANUAL, {'vod': [], 'live': [], 'intl': []})


def _write_manual(cfg, reason):
    """回写 JSON + 尽力 git commit（失败不影响保存）"""
    tmp = MANUAL + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=1)
    shutil.move(tmp, MANUAL)
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
    steps = body.get('steps') or ['01_fetch', '02_probe', '03_dedupe', '04_classify',
                                  '05_verify', '06_search', '07_build', '08_deploy']
    deploy = bool(body.get('deploy'))
    skip_probe = bool(body.get('skip_probe'))
    if skip_probe:
        steps = [s for s in steps if s not in ('02_probe', '05_verify', '06_search')]
    if not deploy:
        steps = [s for s in steps if s != '08_deploy']

    # 并发保护：已有 running 且进程还在，拒绝
    for r in run_dirs()[:3]:
        st = run_state(r)
        if st.get('status') == 'running' and pid_alive(st.get('pid') or 0):
            raise HTTPException(409, f'已有运行中的任务 {r}')

    run_id = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    os.makedirs(os.path.join(RUNS, run_id), exist_ok=True)
    logp = os.path.join(RUNS, run_id, 'driver.log')
    env = dict(os.environ)
    env['STEP08_DEPLOY'] = '1' if deploy else '0'
    cmd = [PY, PIPELINE, '--run-id', run_id, '--steps', ','.join(steps)]
    with open(logp, 'w') as fh:
        p = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=fh,
                             stderr=subprocess.STDOUT, start_new_session=True)
    st = {'run_id': run_id, 'status': 'running', 'pid': p.pid,
          'started': datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S'),
          'steps': [{'step': s, 'rc': None} for s in steps], 'counters': {},
          'requested': {'deploy': deploy, 'skip_probe': skip_probe, 'steps': steps}}
    with open(os.path.join(RUNS, run_id, 'run.json'), 'w', encoding='utf-8') as fh:
        json.dump(st, fh, ensure_ascii=False, indent=1)
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
    return {'artifacts': cfg.get('artifacts') or [], 'buckets': _bucket_names(),
            'groups': _bucket_groups(), 'pools': list(VALID_POOLS),
            'note': 'pool=clean 三层全通池 / full 全量池；buckets=all 表示不限制分类'}


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
        if not f.endswith('.json'):
            errs.append(f'产物「{i}」的文件名必须 .json 结尾')
        if f in files:
            errs.append(f'文件名「{f}」重复')
        files.add(f)
        typ = a.get('type') or 'list'
        if typ not in ('list', 'agg'):
            errs.append(f'产物「{i}」的 type 只能是 list（直连站列表）或 agg（聚合站）')
        if typ == 'agg' and (a.get('group') or 'movie') not in ('movie', 'adult'):
            errs.append(f'产物「{i}」的 group 只能是 movie/adult')
        if typ == 'list' and a.get('pool') not in VALID_POOLS:
            errs.append(f'产物「{i}」的 pool 只能是 clean/full')
        b = a.get('buckets')
        if b != 'all':
            if not isinstance(b, list):
                errs.append(f'产物「{i}」的 buckets 必须是 all 或分类数组')
            else:
                allowed = _buckets_for(ART_GROUP.get(a.get('group') or 'movie', 'other'))
                unknown = [x for x in b if x not in allowed]
                if unknown:
                    errs.append(f'产物「{i}」含未知分类：{unknown}（分类以「分类」tab 为准）')
        for k in ('clip', 'file'):
            if '..' in str(a.get(k) or ''):
                errs.append(f'产物「{i}」的 {k} 含非法路径')
    if errs:
        raise HTTPException(400, '；'.join(errs[:6]))
    payload = {'note': 'GUI 可编辑；改完重跑 07 生成生效', 'artifacts': arts}
    tmp = ART_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    shutil.move(tmp, ART_FILE)
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
    with open(os.path.join(dst, 'meta.json'), 'w', encoding='utf-8') as fh:
        json.dump({'id': pre, 'created': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                   'run_id': 'pre-restore', 'files': saved}, fh, ensure_ascii=False, indent=1)
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
    with open(CATEGORIES, 'w', encoding='utf-8') as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=1)
    try:
        subprocess.run(['git', 'add', 'config/categories.json'], cwd=REPO, capture_output=True, timeout=20)
        subprocess.run(['git', '-c', 'user.name=fongmi-admin', '-c', 'user.email=admin@local',
                        'commit', '-q', '-m', 'ui: 更新分类桶'], cwd=REPO, capture_output=True, timeout=20)
    except Exception:
        pass
    return {'ok': True, 'warnings': w, 'note': '配置已保存；下次 07_build 生效'}


# ---------- 静态页 ----------
app.mount('/static', StaticFiles(directory=os.path.join(HOME, 'static')), name='static')


@app.get('/')
def index():
    return FileResponse(os.path.join(HOME, 'static', 'index.html'))
