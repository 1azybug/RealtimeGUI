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
from holo_agent import HoloComputerAgent, TrajectoryRecorder  # noqa: E402
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("holo_repro")


def parse_args() -> argparse.Namespace:
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
    p.add_argument("--reasoning_effort", default="medium")
    p.add_argument("--image_budget", type=int, default=3)
    p.add_argument("--pause", type=float, default=1.0, help="sleep after each action")
    p.add_argument("--screen_width", type=int, default=1920)
    p.add_argument("--screen_height", type=int, default=1080)
    p.add_argument("--sleep_after_reset", type=float, default=60.0)
    return p.parse_args()


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
    env.reset(task_config=example)
    time.sleep(args.sleep_after_reset)  # let the VM/app settle

    cenv = OSWorldComputerEnv(env, instruction, pause=args.pause)
    # Generic, env-agnostic recording lives in the Agent package and is shared by
    # every runner: traj.jsonl + observation screenshots + the system prompt.
    recorder = TrajectoryRecorder(example_result_dir)
    agent = HoloComputerAgent(
        client=client,
        model=args.model,
        env=cenv,
        max_steps=args.max_steps,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
        image_budget=args.image_budget,
        on_step=recorder.on_step,
    )
    recorder.dump_system_prompt(agent.system_prompt())

    try:
        env.controller.start_recording()
    except Exception as e:  # noqa: BLE001
        logger.warning("start_recording failed: %s", e)

    summary = agent.run()
    answer = summary.get("answer")
    logger.info("agent finished: %s answer=%r", summary, answer)

    # Translate the agent's final answer into an OSWorld special action so the
    # evaluator (esp. the 'infeasible' func) sees it in action_history. If the
    # agent answered and the text declares infeasibility -> FAIL, else DONE.
    if answer is not None:
        if _INFEASIBLE_RE.search(answer):
            logger.info("answer declares infeasible -> FAIL")
            env.step("FAIL", args.pause)
        else:
            env.step("DONE", args.pause)

    time.sleep(20)  # let the environment settle before evaluation
    result = env.evaluate()
    logger.info("[result] %s/%s = %.2f", domain, example_id, result)

    with open(result_path, "w", encoding="utf-8") as f:
        f.write(f"{result}\n")
    try:
        env.controller.end_recording(os.path.join(example_result_dir, "recording.mp4"))
    except Exception as e:  # noqa: BLE001
        logger.warning("end_recording failed: %s", e)

    # Render the self-contained HTML replay (observation + reticle + note/thought/action).
    try:
        with open(os.path.join(example_result_dir, "report.html"), "w", encoding="utf-8") as f:
            f.write(holo_report.build_html(example_result_dir))
    except Exception as e:  # noqa: BLE001
        logger.warning("report generation failed: %s", e)
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
