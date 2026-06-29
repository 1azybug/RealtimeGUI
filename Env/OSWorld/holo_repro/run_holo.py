"""Run the decoupled Holo agent on OSWorld-Verified (docker provider).

Thin assembly layer — it owns NO agent logic and NO desktop logic:
  * environment side  -> OSWorld ``DesktopEnv`` wrapped by ``OSWorldComputerEnv``
  * agent side        -> ``holo_agent.HoloComputerAgent`` (installed package, untouched)

For each task: reset the VM, wrap it as a ComputerEnv, let the agent run its
official loop until it calls ``answer``, then translate that final answer into the
OSWorld special action needed for scoring (DONE, or FAIL if the answer declares
the task infeasible — same convention as mm_agents/surferH/surfer_agent.py) and
call ``env.evaluate()``.

Usage (run inside the `osworld` conda env, with Holo-3.1-4B served on :8002):
  python holo_repro/run_holo.py --domain os --max_tasks 1            # smoke test
  python holo_repro/run_holo.py                                      # full 369
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time

# The OSWorld adapter sits next to this script; the agent (holo_agent) and the
# contract (computer_env) are installed packages. We add this script's dir (for
# osworld_computer_env) and the OSWorld repo root (for desktop_env) to sys.path,
# so the runner works whether or not cwd is the OSWorld root.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))  # OSWorld repo root (has desktop_env/)

# localhost vLLM must bypass the clash proxy.
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

from openai import OpenAI  # noqa: E402

from desktop_env.desktop_env import DesktopEnv  # noqa: E402
from holo_agent import SYSTEM_PROMPTS, HoloComputerAgent, TrajectoryRecorder  # noqa: E402
from holo_agent import report as holo_report  # noqa: E402
from osworld_computer_env import OSWorldComputerEnv  # noqa: E402

# Global safety net: huggingface.co is unreachable here (and the clash proxy is
# unreliable), so route EVERY requests call to the mirror — not just the few
# download sites in setup.py, but also the evaluator/getter downloads that fetch
# reference files at scoring time (their URLs come from task configs, so they
# can't be patched statically). Runs in each spawn worker (re-imports this module).
_HF_MIRROR = os.environ.get("OSWORLD_HF_MIRROR")
if _HF_MIRROR:
    import requests as _rq  # noqa: E402

    _orig_session_request = _rq.sessions.Session.request

    def _mirrored_request(self, method, url, *args, **kwargs):
        if isinstance(url, str) and "huggingface.co" in url:
            url = url.replace("huggingface.co", _HF_MIRROR)
        return _orig_session_request(self, method, url, *args, **kwargs)

    _rq.sessions.Session.request = _mirrored_request

# Same infeasibility convention as the cloud agent (surferH/surfer_agent.py:53):
# if the final answer declares the task infeasible, score via OSWorld's FAIL path.
_INFEASIBLE_RE = re.compile(r"task.{0,4}infeasible|infeasible|cannot be (completed|done)|not possible", re.IGNORECASE)


def _task_feasibility(example: dict) -> tuple[bool, str]:
    """Whether an OSWorld task is OFFICIALLY infeasible, from its evaluator ``func``.

    OSWorld tags ~29/369 tasks as infeasible: their evaluator func is (or includes)
    ``"infeasible"`` and success means the agent correctly DECLINES rather than acts.
    Returns ``(is_infeasible, func_str)``. This is OSWorld-specific knowledge and so
    lives here in the runner (Env side), never in the generic agent/recorder.
    """
    ev = example.get("evaluator", {}) or {}
    func = ev.get("func")
    func_str = ",".join(func) if isinstance(func, list) else str(func or "")
    return ("infeasible" in func_str), func_str


# --- Network health gate (gated on HOLO_NET_GATE=1; no-op otherwise) ----------------
# The home host that feeds this box internet occasionally blips. A web task that runs
# during a blip fails for ENV reasons, not model ones. When enabled, we probe the
# internet (direct, same upstream path the VM uses) before each task and WAIT out any
# outage so a task is never run — nor scored 0 — while the network is down. The probe
# result is recorded in meta.json so any attempt run while net was down is auditable.
# Off by default => zero behavioural change for anyone else's reproduction.
_NET_GATE = os.environ.get("HOLO_NET_GATE") == "1"
# Default probe = gstatic's generate_204: tiny, and empirically far more reliable through
# a high-latency proxy than google.com/generate_204 (which RemoteDisconnects on a slow
# path). Override with HOLO_NET_PROBE. The home-VPN path can be SLOW and lossy (measured
# 5–20s/req with occasional disconnects), so the probe timeout is GENEROUS and tunable via
# HOLO_NET_TIMEOUT — a slow answer still means "up". (Earlier 6–8s timeouts false-paused.)
_NET_PROBE_URL = os.environ.get("HOLO_NET_PROBE", "http://www.gstatic.com/generate_204")
_NET_TIMEOUT = float(os.environ.get("HOLO_NET_TIMEOUT", "25"))
_VM_PROXY = os.environ.get("HOLO_VM_PROXY")  # host relay the VM routes through (geo fix)


def _net_ok(timeout: float = None) -> bool:
    """Probe the home host's network health via the host proxy (http_proxy=7897).

    The host has no usable DIRECT internet — it (and, through the same home host, the
    VM) reaches the web only while that home-host link is up. The 7897 proxy's health is
    therefore the right single signal for "is the network up": if it answers, the home
    host is online and the VM can reach the web; if it times out, everything is down.
    urlopen() honours the http_proxy/https_proxy env the runner already exports.
    """
    import urllib.request
    if timeout is None:
        timeout = _NET_TIMEOUT
    # When the VM geo fix is on, probe through the SAME path the VM uses (the host relay
    # at HOLO_VM_PROXY -> 7897). That way the gate pauses if EITHER the home VPN/7897 OR
    # the relay is down — not just clash. Otherwise probe via the host proxy env.
    try:
        if _VM_PROXY:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": _VM_PROXY, "https": _VM_PROXY}))
            with opener.open(_NET_PROBE_URL, timeout=timeout) as r:
                return 200 <= getattr(r, "status", 200) < 400
        with urllib.request.urlopen(_NET_PROBE_URL, timeout=timeout) as r:
            return 200 <= getattr(r, "status", 200) < 400
    except Exception:  # noqa: BLE001
        return False


def _net_stable(need: int = 1, tries: int = 2, gap: float = 1.0) -> bool:
    """Is the path usable RIGHT NOW? The home-VPN path is slow and lossy (5–20s/req,
    occasional disconnects), so 'N pristine probes in a row' never passes here and would
    false-pause forever. Instead: usable if it answers at least `need` time(s) within
    `tries` generous-timeout attempts. A slow-but-successful answer counts as up. The
    mid-task monitor (below) is the real safety net for a drop AFTER the task starts."""
    ok = 0
    for i in range(tries):
        if _net_ok():
            ok += 1
            if ok >= need:
                return True
        if i < tries - 1:
            time.sleep(gap)
    return False


def _wait_for_net(max_wait: int = 1200) -> bool:
    """If gating is on, block until the internet is STABLY reachable (or max_wait)."""
    if not _NET_GATE:
        return True
    waited = 0
    while not _net_stable():
        if waited >= max_wait:
            logger.warning("[net-gate] still unstable after %ds; proceeding anyway", waited)
            return False
        logger.warning("[net-gate] network down/unstable — pausing task start (waited %ds)", waited)
        time.sleep(20)
        waited += 20
    return True


def _net_monitor(stop_event, state: dict, period: float = 30.0) -> None:
    """Probe the network during the task; set state['dropped'] only after 2 CONSECUTIVE
    failures — on this lossy path a lone missed probe is routine and is NOT a real outage,
    so flagging on a single miss would falsely invalidate good runs.

    A start-of-task probe is insufficient when the tunnel drops mid-task (the web fails
    but net_ok already read True). This runs for the whole task so meta.json reflects
    whether the network really dropped during it."""
    fails = 0
    while not stop_event.is_set():
        if _net_ok():
            fails = 0
        else:
            fails += 1
            if fails >= 2:
                state["dropped"] = True
        stop_event.wait(period)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("holo_repro")


# --- Live console tracing (gated on --live; for serial human debugging) --------------
def _fmt_action(tool_call) -> str:
    """One-line, human-readable form of the model's chosen action, e.g.
    click(x=512, y=300, element='Search button')  /  wait(seconds=20)  /  answer('done')."""
    p = tool_call.model_dump()
    name = p.pop("tool_name", "?")
    inner = ", ".join(f"{k}={v!r}" for k, v in p.items())
    return f"{name}({inner})"


def _print_task_header(domain, example_id, instruction, result_dir, idx=None, total=None):
    pos = f"  [{idx}/{total}]" if idx is not None else ""
    bar = "=" * 78
    print(f"\n{bar}\n"
          f"TASK   {domain}/{example_id}{pos}\n"
          f"GOAL   {instruction}\n"
          f"DIR    {os.path.abspath(result_dir)}\n"
          f"TRAJ   {os.path.abspath(os.path.join(result_dir, 'traj.jsonl'))}\n"
          f"SHOTS  {os.path.abspath(result_dir)}/step_*.png\n"
          f"REPORT {os.path.abspath(os.path.join(result_dir, 'report.html'))}   (任务结束后生成)\n"
          f"{bar}", flush=True)


def _make_live_on_step(recorder, result_dir):
    """Wrap the recorder's on_step so each step ALSO prints note/thought/action live."""
    inner = recorder.on_step

    def _cb(step_idx, image, step, info, reasoning):
        tc = getattr(step, "tool_call", None)
        action = _fmt_action(tc) if tc is not None else "?"
        note = (step.note or "").strip()
        print(f"\n── step {step_idx} ───────────────────────────────────────────────", flush=True)
        if note:
            print(f"  note    : {note}", flush=True)
        print(f"  thought : {step.thought}", flush=True)
        print(f"  action  : {action}", flush=True)
        print(f"  shot    : {os.path.join(os.path.abspath(result_dir), f'step_{step_idx}.png')}", flush=True)
        return inner(step_idx, image, step, info, reasoning)

    return _cb


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="Holo-3.1-4B")
    p.add_argument("--base_url", default="http://127.0.0.1:8002/v1")
    p.add_argument(
        "--base_urls",
        default=None,
        help="comma-separated vLLM endpoints; workers are assigned round-robin "
        "(overrides --base_url). e.g. http://127.0.0.1:8002/v1,http://127.0.0.1:8003/v1",
    )
    p.add_argument("--workers", type=int, default=1, help="parallel workers (each owns one VM/container)")
    p.add_argument("--api_key", default="EMPTY")
    p.add_argument("--test_meta", default="evaluation_examples/test_all.json")
    p.add_argument("--examples_dir", default="evaluation_examples/examples")
    p.add_argument("--result_dir", default="results")
    p.add_argument("--domain", default="all", help="single domain or 'all'")
    p.add_argument("--example_id", default=None, help="run one specific example id")
    p.add_argument("--max_tasks", type=int, default=0, help="0 = no limit")
    p.add_argument("--max_steps", type=int, default=100)
    p.add_argument("--temperature", type=float, default=0.8)
    p.add_argument("--prompt", default="v2", choices=sorted(SYSTEM_PROMPTS),
                   help="system-prompt variant (v1=baseline, v2=behavioral). For A/B runs.")
    p.add_argument("--reasoning_effort", default="medium")
    p.add_argument("--image_budget", type=int, default=3)
    p.add_argument("--no_report", action="store_true", help="skip report.html generation (saves disk/time)")
    p.add_argument("--no_recording", action="store_true", help="skip mp4 screen recording (saves disk/time)")
    p.add_argument("--pause", type=float, default=1.0, help="sleep after each action")
    p.add_argument("--screen_width", type=int, default=1920)
    p.add_argument("--screen_height", type=int, default=1080)
    p.add_argument("--sleep_after_reset", type=float, default=60.0)
    p.add_argument("--live", action="store_true",
                   help="print a task header + each step's note/thought/action live to the "
                        "console (for serial debugging). Best with --workers 1.")
    return p.parse_args(argv)


def select_tasks(args: argparse.Namespace) -> list[tuple[str, str]]:
    with open(args.test_meta, "r", encoding="utf-8") as f:
        meta = json.load(f)
    tasks: list[tuple[str, str]] = []
    domains = meta.keys() if args.domain == "all" else [args.domain]
    for d in domains:
        for ex in meta.get(d, []):
            if args.example_id and ex != args.example_id:
                continue
            tasks.append((d, ex))
    if args.max_tasks > 0:
        tasks = tasks[: args.max_tasks]
    return tasks


def run_one(args, env, client, domain, example_id) -> float | None:
    config_file = os.path.join(args.examples_dir, domain, f"{example_id}.json")
    with open(config_file, "r", encoding="utf-8") as f:
        example = json.load(f)
    instruction = example["instruction"]
    is_infeasible, evaluator_func = _task_feasibility(example)
    # Geo fix (gated): when HOLO_VM_PROXY is set, route EVERY task's VM through it (the
    # VM defaults to the campus network / China geo; many web tasks need the home US
    # proxy). Triggers _proxy_setup before Chrome. No-op when HOLO_VM_PROXY is unset.
    if os.environ.get("HOLO_VM_PROXY"):
        example["proxy"] = True

    example_result_dir = os.path.join(
        args.result_dir, "pyautogui", "screenshot", args.model, domain, example_id
    )
    os.makedirs(example_result_dir, exist_ok=True)

    # Resume: skip already-scored tasks.
    result_path = os.path.join(example_result_dir, "result.txt")
    if os.path.exists(result_path):
        with open(result_path) as f:
            prev = f.read().strip()
        logger.info("[skip] %s/%s already scored: %s", domain, example_id, prev)
        try:
            return float(prev)
        except ValueError:
            return None

    logger.info("[task] %s/%s :: %s", domain, example_id, instruction)
    if getattr(args, "live", False):
        _print_task_header(domain, example_id, instruction, example_result_dir)
    net_ok_at_start = _wait_for_net() if _NET_GATE else None  # block out network outages (gated)
    env.reset(task_config=example)
    time.sleep(args.sleep_after_reset)  # let the VM/app settle

    cenv = OSWorldComputerEnv(env, instruction, pause=args.pause)
    # Generic, env-agnostic recording lives in the Agent package and is shared by
    # every runner: traj.jsonl + observation screenshots + the system prompt.
    recorder = TrajectoryRecorder(example_result_dir)
    on_step = (_make_live_on_step(recorder, example_result_dir)
               if getattr(args, "live", False) else recorder.on_step)
    agent = HoloComputerAgent(
        client=client,
        model=args.model,
        env=cenv,
        max_steps=args.max_steps,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
        image_budget=args.image_budget,
        on_step=on_step,
        system_prompt_template=SYSTEM_PROMPTS[args.prompt],
    )
    recorder.dump_system_prompt(agent.system_prompt())

    if not args.no_recording:
        try:
            env.controller.start_recording()
        except Exception as e:  # noqa: BLE001
            logger.warning("start_recording failed: %s", e)

    # Monitor the network for the WHOLE task (the tunnel flaps mid-task), so net_ok
    # reflects continuous availability, not just a probe at start. Gated on net-gate.
    import threading
    _net_state = {"dropped": False}
    _net_stop = threading.Event()
    if _NET_GATE:
        threading.Thread(target=_net_monitor, args=(_net_stop, _net_state), daemon=True).start()

    summary = agent.run()

    _net_stop.set()
    # net_ok is honest only if the net was up at start AND never dropped during the task.
    net_ok_during = (net_ok_at_start is not False) and not _net_state["dropped"]
    answer = summary.get("answer")
    logger.info("agent finished: %s answer=%r net_dropped=%s", summary, answer, _net_state["dropped"])

    # Infra-failure guard: an empty trajectory means the agent never recorded a single
    # step — it never got a usable observation (VM not ready, model endpoint blip, etc.).
    # That is an ENVIRONMENT failure, not a model result; persisting a 0 would pollute
    # scores and never_solved. Leave the task unscored (no result.txt) so resume re-runs
    # it cleanly later, and drop the empty recorder dir's traj so it isn't counted.
    traj_lines = 0
    _tp = os.path.join(example_result_dir, "traj.jsonl")
    if os.path.exists(_tp):
        with open(_tp, encoding="utf-8") as _f:
            traj_lines = sum(1 for _ in _f)
    if traj_lines == 0 and not summary.get("finished_by_agent"):
        logger.warning("[infra-fail] %s/%s produced 0 steps (VM/model not ready) — "
                       "not scoring, will re-run on resume", domain, example_id)
        return None

    # Translate the agent's final answer into an OSWorld special action so the
    # evaluator (esp. the 'infeasible' func) sees it in action_history. If the
    # agent answered and the text declares infeasibility -> FAIL, else DONE.
    model_declared_infeasible = bool(answer is not None and _INFEASIBLE_RE.search(answer))
    if answer is not None:
        if model_declared_infeasible:
            logger.info("answer declares infeasible -> FAIL")
            env.step("FAIL", args.pause)
        else:
            env.step("DONE", args.pause)

    time.sleep(20)  # let the environment settle before evaluation
    result = env.evaluate()
    logger.info(
        "[result] %s/%s = %.2f (infeasible_task=%s, model_declined=%s)",
        domain, example_id, result, is_infeasible, model_declared_infeasible,
    )

    with open(result_path, "w", encoding="utf-8") as f:
        f.write(f"{result}\n")

    # Sidecar feasibility metadata for debugging: lets you tell, at a glance, whether
    # a 0 is on an OFFICIALLY-INFEASIBLE task (where success = correctly declining)
    # vs a feasible task that genuinely failed. Written via the generic recorder hook
    # so the report can surface it; result.txt stays a pure float (resume/aggregate).
    recorder.dump_meta({
        "domain": domain,
        "example_id": example_id,
        "score": result,
        "prompt_variant": args.prompt,
        "infeasible_task": is_infeasible,
        "net_ok": (net_ok_during if _NET_GATE else None),   # up at start AND never dropped during the task
        "net_ok_at_start": net_ok_at_start,
        "net_dropped_during": (_net_state["dropped"] if _NET_GATE else None),
        "model_declared_infeasible": model_declared_infeasible,
        "evaluator_func": evaluator_func,
        "finished_by_agent": summary.get("finished_by_agent"),
        "steps": summary.get("steps"),
        "answer": answer,
        "banner": (
            {"level": "warn",
             "text": "官方标注：此任务不可行 (INFEASIBLE)。正确行为是模型声明无法完成；"
                     "得分衡量的是模型是否正确拒绝，而非真的执行成功。"}
            if is_infeasible else None
        ),
        "facts": {
            "task": "INFEASIBLE (official)" if is_infeasible else "feasible",
            "model declined": "yes" if model_declared_infeasible else "no",
        },
    })

    if not args.no_recording:
        try:
            env.controller.end_recording(os.path.join(example_result_dir, "recording.mp4"))
        except Exception as e:  # noqa: BLE001
            logger.warning("end_recording failed: %s", e)

    # Render the self-contained HTML replay (observation + reticle + note/thought/action).
    if not args.no_report:
        try:
            with open(os.path.join(example_result_dir, "report.html"), "w", encoding="utf-8") as f:
                f.write(holo_report.build_html(example_result_dir))
        except Exception as e:  # noqa: BLE001
            logger.warning("report generation failed: %s", e)
    if getattr(args, "live", False):
        verdict = "✅ PASS" if result == 1 else "❌ FAIL"
        print(f"\nRESULT {domain}/{example_id} = {result:.2f}  {verdict}"
              f"   ({summary.get('steps')} steps, finished_by_agent={summary.get('finished_by_agent')})\n"
              f"REPORT {os.path.abspath(os.path.join(example_result_dir, 'report.html'))}\n", flush=True)
    return float(result)


def _already_done(args, domain, example_id) -> bool:
    rp = os.path.join(args.result_dir, "pyautogui", "screenshot", args.model, domain, example_id, "result.txt")
    return os.path.exists(rp)


def _make_env(args):
    return DesktopEnv(
        provider_name="docker",
        path_to_vm=None,
        action_space="pyautogui",
        screen_size=(args.screen_width, args.screen_height),
        headless=True,
        os_type="Ubuntu",
        require_a11y_tree=False,
        # Only enable OSWorld's proxy hook when our geo fix is on (HOLO_VM_PROXY set);
        # otherwise default (False) => upstream behaviour, no proxy setup.
        enable_proxy=bool(os.environ.get("HOLO_VM_PROXY")),
    )


def worker_loop(worker_id: int, base_url: str, task_queue, args) -> None:
    """One parallel worker: owns a single DesktopEnv/VM, pulls tasks until drained."""
    import queue as _queue

    wlog = logging.getLogger(f"holo_repro.w{worker_id}")
    wlog.info("worker %d starting on %s", worker_id, base_url)
    client = OpenAI(base_url=base_url, api_key=args.api_key)
    try:
        env = _make_env(args)
    except Exception as e:  # noqa: BLE001
        wlog.exception("worker %d failed to start its VM: %s", worker_id, e)
        return
    try:
        while True:
            try:
                domain, example_id = task_queue.get_nowait()
            except _queue.Empty:
                break
            try:
                run_one(args, env, client, domain, example_id)
            except Exception as e:  # noqa: BLE001
                wlog.exception("task %s/%s crashed: %s", domain, example_id, e)
    finally:
        try:
            env.close()
        except Exception:  # noqa: BLE001
            pass
    wlog.info("worker %d done", worker_id)


def aggregate(args, tasks) -> None:
    scores = []
    for domain, example_id in tasks:
        rp = os.path.join(args.result_dir, "pyautogui", "screenshot", args.model, domain, example_id, "result.txt")
        if os.path.exists(rp):
            try:
                scores.append(float(open(rp).read().strip()))
            except ValueError:
                pass
    if scores:
        logger.info("DONE. mean score over %d/%d tasks = %.4f", len(scores), len(tasks), sum(scores) / len(scores))
    else:
        logger.info("DONE. no scores recorded.")


def main() -> None:
    import multiprocessing as mp

    args = parse_args()
    tasks = select_tasks(args)
    base_urls = [u.strip() for u in args.base_urls.split(",")] if args.base_urls else [args.base_url]
    workers = max(1, args.workers)
    pending = [t for t in tasks if not _already_done(args, *t)]
    logger.info(
        "selected %d task(s), %d pending; %d worker(s) over %d endpoint(s): %s",
        len(tasks), len(pending), workers, len(base_urls), base_urls,
    )

    if not pending:
        aggregate(args, tasks)
        return

    if workers == 1:
        # Serial path (no extra processes).
        client = OpenAI(base_url=base_urls[0], api_key=args.api_key)
        env = _make_env(args)
        try:
            for domain, example_id in pending:
                try:
                    run_one(args, env, client, domain, example_id)
                except Exception as e:  # noqa: BLE001
                    logger.exception("task %s/%s crashed: %s", domain, example_id, e)
        finally:
            try:
                env.close()
            except Exception:  # noqa: BLE001
                pass
        aggregate(args, tasks)
        return

    ctx = mp.get_context("spawn")
    task_queue = ctx.Queue()
    for t in pending:
        task_queue.put(t)
    procs = []
    for i in range(workers):
        p = ctx.Process(target=worker_loop, args=(i, base_urls[i % len(base_urls)], task_queue, args), daemon=False)
        p.start()
        procs.append(p)
        time.sleep(8)  # stagger VM boots so docker port allocation / startup don't thundering-herd
    for p in procs:
        p.join()
    aggregate(args, tasks)


if __name__ == "__main__":
    main()
