#!/usr/bin/env python3
"""run_step.py —— 流水线单步执行器（GUI 与 cron 共用）

用法:
  python3 pipeline/run_step.py --run-id 20261114-0500-a1 --step 02_probe
  python3 pipeline/run_step.py --run-id xxx --pipeline            # 顺序跑 01..08
  python3 pipeline/run_step.py --list                             # 列出可跑步骤

约定:
  每步脚本写成 scripts/steps/NN_name.sh，最后打印一行
      ##COUNTERS## {"k": v}
  产物:
      state/runs/<run_id>/<step>.log     完整 stdout+stderr
      state/runs/<run_id>/<step>.json    {step, rc, started, finished, duration_ms, counters}
      state/runs/<run_id>/run.json       整轮汇总（--pipeline 时维护）

退出码语义（GUI 据此决定"可重试 / 硬失败"）:
      0  成功
     10  无变化（例如未开启部署）
     20  网络类失败，可重试
     30  硬失败，需人工
"""
import argparse, json, os, subprocess, sys, time, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEPS_DIR = os.path.join(BASE, 'scripts', 'steps')
RUNS = os.path.join(BASE, 'state', 'runs')

ORDER = ['01_fetch', '02_probe', '03_dedupe', '04_classify',
         '05_verify', '06_search', '07_build', '08_deploy']


def now():
    return datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')


def step_path(step):
    return os.path.join(STEPS_DIR, step + '.sh')


def list_steps():
    return [s for s in ORDER if os.path.exists(step_path(s))]


def run_one(run_id, step, extra_env=None):
    rd = os.path.join(RUNS, run_id)
    os.makedirs(rd, exist_ok=True)
    logf = os.path.join(rd, step + '.log')
    jsf = os.path.join(rd, step + '.json')
    if not os.path.exists(step_path(step)):
        raise SystemExit(f'!! 没有这个 step: {step}')

    env = dict(os.environ)
    env.setdefault('PYTHONUNBUFFERED', '1')
    if extra_env:
        env.update(extra_env)

    t0 = time.time()
    started = now()
    counters, rc = {}, 0
    with open(logf, 'w', encoding='utf-8') as fh:
        p = subprocess.Popen(['bash', step_path(step)], cwd=BASE, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)
        for line in p.stdout:
            if line.startswith('##COUNTERS##'):
                try:
                    counters = json.loads(line[len('##COUNTERS##'):].strip())
                except Exception:
                    pass
                continue
            fh.write(line)
            fh.flush()
            sys.stdout.write(line)
            sys.stdout.flush()
        rc = p.wait()

    rec = {'step': step, 'rc': rc, 'started': started, 'finished': now(),
           'duration_ms': int((time.time() - t0) * 1000),
           'counters': counters,
           'class': 'ok' if rc == 0 else 'noop' if rc == 10 else 'retryable' if rc == 20 else 'hard'}
    with open(jsf, 'w', encoding='utf-8') as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
    print(f"\n=== {step} rc={rc} ({rec['class']}) {rec['duration_ms']}ms {counters}")
    return rec


def run_pipeline(run_id, steps, extra_env=None):
    rd = os.path.join(RUNS, run_id)
    os.makedirs(rd, exist_ok=True)
    summary = {'run_id': run_id, 'started': now(), 'status': 'running',
               'steps': [], 'counters': {}}
    _write(os.path.join(rd, 'run.json'), summary)
    t0 = time.time()
    for step in steps:
        rec = run_one(run_id, step, extra_env)
        summary['steps'].append(rec)
        summary['counters'].update(rec['counters'])
        if rec['class'] == 'retryable':
            print(f'--- {step} 网络类失败，重试一次')
            rec2 = run_one(run_id, step, extra_env)
            summary['steps'].append(rec2)
            summary['counters'].update(rec2['counters'])
            rec = rec2
        if rec['class'] == 'hard':
            summary['status'] = 'failed'
            break
    else:
        summary['status'] = 'ok'
    summary['finished'] = now()
    summary['duration_ms'] = int((time.time() - t0) * 1000)
    _write(os.path.join(rd, 'run.json'), summary)
    print(f"\n=== 本轮 {summary['status']} 用时 {summary['duration_ms']}ms")
    return summary


def _write(path, obj):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-id')
    ap.add_argument('--step')
    ap.add_argument('--pipeline', action='store_true')
    ap.add_argument('--from-step')
    ap.add_argument('--steps', help='逗号分隔的自定义步骤集，按给定顺序跑')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--env', action='append', default=[], help='K=V，可多次')
    a = ap.parse_args()

    if a.list:
        for s in list_steps():
            print(s)
        return

    extra = {}
    for kv in a.env:
        if '=' in kv:
            k, v = kv.split('=', 1)
            extra[k] = v

    if not a.run_id:
        a.run_id = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')

    if a.steps:
        steps = [x.strip() for x in a.steps.split(',') if x.strip()]
        for st in steps:
            if not os.path.exists(step_path(st)):
                raise SystemExit(f'!! 未知 step: {st}')
        run_pipeline(a.run_id, steps, extra)
        return

    if a.pipeline:
        steps = list_steps()
        if a.from_step:
            if a.from_step not in steps:
                raise SystemExit(f'!! 未知起始步 {a.from_step}')
            steps = steps[steps.index(a.from_step):]
        run_pipeline(a.run_id, steps, extra)
        return

    if not a.step:
        raise SystemExit('需要 --step 或 --pipeline（或用 --list 看步骤）')
    rec = run_one(a.run_id, a.step, extra)
    sys.exit(rec['rc'])


if __name__ == '__main__':
    main()
