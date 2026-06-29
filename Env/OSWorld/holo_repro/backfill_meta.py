"""Backfill ``meta.json`` (task feasibility) + regenerate ``report.html`` for
already-scored OSWorld results.

Newer ``run_holo`` writes a feasibility sidecar (meta.json) and shows an INFEASIBLE
banner in each report. Earlier runs predate that; this one-shot, idempotent tool
backfills them so existing results are debuggable the same way — at a glance you can
tell whether a 0 is on an OFFICIALLY-INFEASIBLE task (success = correctly declining)
or on a feasible task that genuinely failed.

Run from ``Env/OSWorld``:
    python holo_repro/backfill_meta.py                 # meta.json + report.html (needs holo_agent)
    python holo_repro/backfill_meta.py --no-report     # only meta.json (stdlib only)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re

# Same infeasibility convention as run_holo.py (kept inline so --no-report needs
# only the stdlib, no heavy desktop_env/holo_agent import).
_INFEASIBLE_RE = re.compile(
    r"task.{0,4}infeasible|infeasible|cannot be (completed|done)|not possible", re.IGNORECASE
)


def feasibility(example: dict) -> tuple[bool, str]:
    ev = example.get("evaluator", {}) or {}
    func = ev.get("func")
    s = ",".join(func) if isinstance(func, list) else str(func or "")
    return ("infeasible" in s), s


def last_answer(traj_path: str):
    """Reconstruct the agent's final ``answer`` content from traj.jsonl, if any."""
    ans = None
    if not os.path.exists(traj_path):
        return None
    with open(traj_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("tool_name") == "answer":
                ans = (d.get("tool_call") or {}).get("content")
    return ans


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Holo-3.1-4B")
    ap.add_argument("--result_dir", default="results")
    ap.add_argument("--examples_dir", default="evaluation_examples/examples")
    ap.add_argument("--no-report", action="store_true", help="only write meta.json, skip report regen")
    args = ap.parse_args()

    base = os.path.join(args.result_dir, "pyautogui", "screenshot", args.model)
    dirs = sorted(glob.glob(os.path.join(base, "*", "*")))
    n = inf = 0
    for d in dirs:
        if not os.path.isdir(d):
            continue
        example_id = os.path.basename(d)
        domain = os.path.basename(os.path.dirname(d))
        cfg = os.path.join(args.examples_dir, domain, example_id + ".json")
        if not os.path.exists(cfg):
            continue
        example = json.load(open(cfg, encoding="utf-8"))
        is_inf, func = feasibility(example)
        score = None
        rp = os.path.join(d, "result.txt")
        if os.path.exists(rp):
            try:
                score = float(open(rp).read().strip())
            except ValueError:
                pass
        ans = last_answer(os.path.join(d, "traj.jsonl"))
        declined = bool(ans and _INFEASIBLE_RE.search(ans))
        meta = {
            "domain": domain,
            "example_id": example_id,
            "score": score,
            "infeasible_task": is_inf,
            "model_declared_infeasible": declined,
            "evaluator_func": func,
            "answer": ans,
            "banner": (
                {"level": "warn",
                 "text": "官方标注：此任务不可行 (INFEASIBLE)。正确行为是模型声明无法完成；"
                         "得分衡量的是模型是否正确拒绝，而非真的执行成功。"}
                if is_inf else None
            ),
            "facts": {
                "task": "INFEASIBLE (official)" if is_inf else "feasible",
                "model declined": "yes" if declined else "no",
            },
            "backfilled": True,
        }
        json.dump(meta, open(os.path.join(d, "meta.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        n += 1
        inf += int(is_inf)
        if not args.no_report:
            try:
                from holo_agent import report as R  # noqa: PLC0415
                with open(os.path.join(d, "report.html"), "w", encoding="utf-8") as f:
                    f.write(R.build_html(d))
            except Exception as e:  # noqa: BLE001
                print("report regen failed:", d, e)
    print(f"backfilled {n} result dirs, {inf} infeasible-tagged")


if __name__ == "__main__":
    main()
