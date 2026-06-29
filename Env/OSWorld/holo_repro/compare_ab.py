"""Compare the A/B run (v1 baseline prompt vs v2 new prompt) on the subset.

Reads results_ab_v1 / results_ab_v2 result.txt against holo_repro/ab_baseline.json
(which records each task's group + its score in the original full run), and prints a
per-group before/after table. Run from Env/OSWorld.
"""
from __future__ import annotations
import json, os, collections

MODEL = "Holo-3.1-4B"
GROUPS = ["G1_save", "G2_inf_miss", "G2_inf_ok", "G3_win", "G4_long"]


def score_of(result_dir, dom, eid):
    p = os.path.join(result_dir, "pyautogui", "screenshot", MODEL, dom, eid, "result.txt")
    if not os.path.exists(p):
        return None
    try:
        return float(open(p).read().strip())
    except ValueError:
        return None


def main():
    base = json.load(open("holo_repro/ab_baseline.json", encoding="utf-8"))
    rows = []
    for key, info in base.items():
        dom, eid = key.split("/", 1)
        orig = info["baseline"]
        rows.append({
            "domain": dom, "eid": eid, "group": info["group"],
            "orig": float(orig) if orig is not None else None,
            "v1": score_of("results_ab_v1", dom, eid),
            "v2": score_of("results_ab_v2", dom, eid),
        })

    by = collections.defaultdict(list)
    for r in rows:
        by[r["group"]].append(r)

    def avg(xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else None

    print(f"{'group':12} {'n':>3} {'orig':>6} {'v1':>6} {'v2':>6} {'v2-v1':>7}")
    tot = {"v1": [], "v2": [], "orig": []}
    for g in GROUPS:
        rs = by.get(g, [])
        if not rs:
            continue
        o, a, b = avg([r["orig"] for r in rs]), avg([r["v1"] for r in rs]), avg([r["v2"] for r in rs])
        dv = (b - a) if (a is not None and b is not None) else None
        print(f"{g:12} {len(rs):>3} {o:>6.2f} "
              f"{(a if a is not None else float('nan')):>6.2f} "
              f"{(b if b is not None else float('nan')):>6.2f} "
              f"{(dv if dv is not None else float('nan')):>+7.2f}")
        for r in rs:
            tot["orig"].append(r["orig"]); tot["v1"].append(r["v1"]); tot["v2"].append(r["v2"])
    print("-" * 44)
    o, a, b = avg(tot["orig"]), avg(tot["v1"]), avg(tot["v2"])
    print(f"{'ALL':12} {len(rows):>3} {o:>6.2f} {a:>6.2f} {b:>6.2f} {b-a:>+7.2f}")

    done_v1 = sum(1 for r in rows if r["v1"] is not None)
    done_v2 = sum(1 for r in rows if r["v2"] is not None)
    print(f"\ncompleted: v1 {done_v1}/{len(rows)}  v2 {done_v2}/{len(rows)}")
    # per-task detail for the save group (the key mechanistic test)
    print("\n-- G1_save per-task (orig -> v1 -> v2) --")
    def fmt(x):
        return "?" if x is None else f"{x:.2f}"
    for r in by.get("G1_save", []):
        print(f"  {r['domain']:18} {r['eid'][:8]}  "
              f"{fmt(r['orig'])} -> {fmt(r['v1'])} -> {fmt(r['v2'])}")


if __name__ == "__main__":
    main()
