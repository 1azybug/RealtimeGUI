"""Aggregate the multi-sample experiment into CSVs.

Layout produced by run_multi.py:
  results_multi/<prompt>/a<N>/pyautogui/screenshot/Holo-3.1-4B/<domain>/<id>/result.txt

Outputs (in results_multi/):
  summary.csv      — per task: per-prompt score list / mean / max across attempts.
  never_solved.csv — tasks that scored 0 on EVERY attempt (for manual analysis).

Run from Env/OSWorld:  python holo_repro/compare_multi.py
"""
from __future__ import annotations

import csv
import json
import os

MODEL = "Holo-3.1-4B"
PROMPTS = ["v1", "v2"]
MAX_ATTEMPTS = 10


def _osw() -> str:
    # this file lives in Env/OSWorld/holo_repro/
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_score(osw, p, a, dom, eid):
    fp = os.path.join(osw, f"results_multi/{p}/a{a}",
                      "pyautogui", "screenshot", MODEL, dom, eid, "result.txt")
    if os.path.exists(fp):
        try:
            return float(open(fp).read().strip())
        except ValueError:
            return None
    return None


def task_meta(osw):
    m = json.load(open(os.path.join(osw, "evaluation_examples/test_all.json")))
    out = {}
    for dom, ids in m.items():
        for eid in ids:
            cfg = os.path.join(osw, "evaluation_examples/examples", dom, eid + ".json")
            inf, instr = False, ""
            try:
                c = json.load(open(cfg))
                instr = c.get("instruction", "")
                ev = c.get("evaluator", {}) or {}
                func = ev.get("func")
                fs = ",".join(func) if isinstance(func, list) else str(func or "")
                inf = "infeasible" in fs
            except (OSError, ValueError):
                pass
            out[(dom, eid)] = (inf, instr)
    return out


def scores_for(osw, p, dom, eid):
    xs = []
    for a in range(1, MAX_ATTEMPTS + 1):
        s = read_score(osw, p, a, dom, eid)
        if s is not None:
            xs.append(s)
    return xs


COLS = ["domain", "example_id", "infeasible",
        "v1_n", "v1_mean", "v1_max", "v1_scores",
        "v2_n", "v2_mean", "v2_max", "v2_scores",
        "best", "n_total", "solved_ever", "instruction"]


def aggregate(osw=None):
    osw = osw or _osw()
    tm = task_meta(osw)
    rows = []
    for (dom, eid), (inf, instr) in tm.items():
        rec = {"domain": dom, "example_id": eid, "infeasible": inf}
        allsc = []
        for p in PROMPTS:
            xs = scores_for(osw, p, dom, eid)
            rec[f"{p}_n"] = len(xs)
            rec[f"{p}_mean"] = round(sum(xs) / len(xs), 3) if xs else ""
            rec[f"{p}_max"] = max(xs) if xs else ""
            rec[f"{p}_scores"] = ";".join(f"{x:g}" for x in xs)
            allsc += xs
        rec["best"] = max(allsc) if allsc else ""
        rec["n_total"] = len(allsc)
        rec["solved_ever"] = bool(allsc and max(allsc) > 0)
        rec["instruction"] = instr[:160]
        rows.append(rec)
    rows.sort(key=lambda r: (r["domain"], r["example_id"]))

    out_dir = os.path.join(osw, "results_multi")
    os.makedirs(out_dir, exist_ok=True)
    sp = os.path.join(out_dir, "summary.csv")
    with open(sp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(rows)

    ns = [r for r in rows if r["n_total"] > 0 and not r["solved_ever"]]
    nsp = os.path.join(out_dir, "never_solved.csv")
    with open(nsp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(ns)

    def overall(p):
        ms = [r[f"{p}_mean"] for r in rows if r[f"{p}_n"] > 0 and r[f"{p}_mean"] != ""]
        return round(sum(ms) / len(ms), 4) if ms else None

    started = sum(1 for r in rows if r["n_total"] > 0)
    print(f"[aggregate] summary.csv={sp}")
    print(f"[aggregate] never_solved.csv={nsp} (n={len(ns)})")
    print(f"[aggregate] tasks with >=1 attempt: {started}/{len(rows)} | "
          f"per-task-mean v1={overall('v1')} v2={overall('v2')}")
    return sp, nsp


if __name__ == "__main__":
    aggregate()
