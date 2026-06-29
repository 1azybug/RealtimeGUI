"""Multi-sample experiment driver (unattended, hours-long, idempotent).

Design (per user spec):
  * Phase A: every task in test_all.json, prompts v1 AND v2, each 3 attempts.
  * Escalate: tasks that scored 0 on ALL 6 phase-A attempts -> 10 attempts each prompt.
  * never_solved.csv collects tasks that scored 0 on every attempt (up to 20) for analysis.

Each (prompt, attempt) is a separate result dir, so run_holo's built-in resume makes the
whole thing restartable: re-running skips already-scored (task, prompt, attempt) cells.
Aggregation (compare_multi) is re-run after every pass, so the CSVs are always current.

Run from Env/OSWorld:
  python holo_repro/run_multi.py --base_urls http://127.0.0.1:8002/v1,...,:8005/v1 --workers 12
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess

import compare_multi  # same dir

HERE = os.path.dirname(os.path.abspath(__file__))
OSW = os.path.dirname(HERE)
PROMPTS = ["v1", "v2"]


def ensure_relay(pyo):
    """Check (don't provide) the VM's geo path before a pass: 10.200.0.1:7897 must be
    reachable. No-op unless the geo fix (HOLO_VM_PROXY) is on.

    The bridge port is now owned by the home host's SSH reverse tunnel
    (-R 10.200.0.1:7897:127.0.0.1:7897), NOT by a local relay. We must NOT start
    proxy_relay.py here: it would bind 10.200.0.1:7897, and on the next tunnel
    reconnect SSH (ExitOnForwardFailure) couldn't rebind and would exit — killing geo.
    So this only warns if the tunnel looks down; fixing it is a home-host action."""
    if not os.environ.get("HOLO_VM_PROXY"):
        return
    import socket
    try:
        socket.create_connection(("10.200.0.1", 7897), timeout=2).close()
    except OSError:
        print("[relay] WARN: 10.200.0.1:7897 unreachable — SSH reverse tunnel likely "
              "down on the home host; geo-sensitive web tasks will see China locale. "
              "Fix the tunnel on the home host (do NOT start a local relay).", flush=True)


def run_pass(p, a, test_meta, base_urls, workers, pyo, env):
    ensure_relay(pyo)
    rd = f"results_multi/{p}/a{a}"
    log = os.path.join(OSW, f"multi_{p}_a{a}.log")
    cmd = [pyo, "holo_repro/run_holo.py", "--prompt", p, "--result_dir", rd,
           "--test_meta", test_meta, "--workers", str(workers), "--base_urls", base_urls,
           "--no_report", "--no_recording"]
    with open(log, "w") as f:
        subprocess.run(cmd, cwd=OSW, env=env, stdout=f, stderr=subprocess.STDOUT, check=False)


def find_hard(osw):
    """Tasks that scored 0 on every phase-A attempt (v1 a1-3 and v2 a1-3)."""
    tm = compare_multi.task_meta(osw)
    hard = collections.defaultdict(list)
    for (dom, eid) in tm:
        allsc = []
        for p in PROMPTS:
            for a in (1, 2, 3):
                s = compare_multi.read_score(osw, p, a, dom, eid)
                if s is not None:
                    allsc.append(s)
        if allsc and max(allsc) == 0:
            hard[dom].append(eid)
    return hard


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base_urls", required=True)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--pyo", default="/mnt/zhaorunsong/anaconda3/envs/osworld/bin/python")
    args = ap.parse_args()

    env = dict(os.environ)
    env.update({
        "DOCKER_HOST": "unix:///var/run/docker.sock",
        "OSWORLD_FORCE_KVM": "1",
        "http_proxy": "http://127.0.0.1:7897",
        "https_proxy": "http://127.0.0.1:7897",
        "no_proxy": "localhost,127.0.0.1",
        "NO_PROXY": "localhost,127.0.0.1",
    })

    # Phase A — all tasks, both prompts, 3 attempts each.
    for a in (1, 2, 3):
        for p in PROMPTS:
            print(f"[phaseA] prompt={p} attempt={a}", flush=True)
            run_pass(p, a, "evaluation_examples/test_all.json", args.base_urls, args.workers, args.pyo, env)
            compare_multi.aggregate(OSW)

    # Escalate hard tasks to 10 attempts each prompt.
    hard = find_hard(OSW)
    nh = sum(len(v) for v in hard)
    json.dump(hard, open(os.path.join(OSW, "evaluation_examples/test_hard.json"), "w"))
    print(f"[escalate] hard tasks (0 over all 6 phase-A attempts): {nh}", flush=True)
    if nh:
        for a in range(4, 11):
            for p in PROMPTS:
                print(f"[phaseB] prompt={p} attempt={a}", flush=True)
                run_pass(p, a, "evaluation_examples/test_hard.json", args.base_urls, args.workers, args.pyo, env)
                compare_multi.aggregate(OSW)

    compare_multi.aggregate(OSW)
    print("[done] multi-sample complete", flush=True)


if __name__ == "__main__":
    main()
