"""按需为结果目录生成 report.html(多采样为省磁盘带 --no_report 跑,结果里没有 report.html,
但 traj.jsonl + 截图都在,可随时补生成,用于人工判断"模型失败 vs 网络失败")。

挑选(可叠加;不给则匹配全部):
  --domains chrome multi_apps   只给这些域生成(web 任务=网络故障候选)
  --zero-only                   只给 0 分的生成
  --tasks dom/eid ...           指定任务
  --attempts v1/a1 v2/a1 ...    只给这些 prompt/attempt 格生成(默认全部)

生成后每个目录下有 report.html,浏览器打开看;判断是网络问题就 `rm -rf 那个目录`,
然后重启 run_multi(resume)会补跑。

例:
  cd Env/OSWorld
  python3 holo_repro/gen_reports.py --domains chrome multi_apps --zero-only
"""
from __future__ import annotations

import argparse
import glob
import os

MODEL = "Holo-3.1-4B"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result_dir", default="results_multi")
    ap.add_argument("--domains", nargs="*", default=[])
    ap.add_argument("--tasks", nargs="*", default=[])
    ap.add_argument("--attempts", nargs="*", default=[], help="如 v1/a1 v2/a1")
    ap.add_argument("--zero-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="已有 report.html 也重生成")
    args = ap.parse_args()

    from holo_agent import report as R

    task_set = set(args.tasks)
    att_set = set(args.attempts)
    base = os.path.join(args.result_dir, "*", "*", "pyautogui", "screenshot", MODEL, "*", "*")
    made = skipped = 0
    for d in sorted(glob.glob(base)):
        if not os.path.exists(os.path.join(d, "traj.jsonl")):
            continue
        dom = os.path.basename(os.path.dirname(d))
        eid = os.path.basename(d)
        # prompt/attempt = 倒数第 7、6 段（results_multi/<p>/<a>/pyautogui/...）
        parts = d.split(os.sep)
        pa = f"{parts[-7]}/{parts[-6]}"
        if args.domains and dom not in args.domains:
            continue
        if task_set and f"{dom}/{eid}" not in task_set:
            continue
        if att_set and pa not in att_set:
            continue
        if args.zero_only:
            rp = os.path.join(d, "result.txt")
            try:
                if not os.path.exists(rp) or float(open(rp).read().strip()) != 0:
                    continue
            except ValueError:
                continue
        out = os.path.join(d, "report.html")
        if os.path.exists(out) and not args.force:
            skipped += 1
            continue
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(R.build_html(d))
            made += 1
            print(f"  {pa}  {dom}/{eid[:8]}  -> report.html")
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {pa} {dom}/{eid[:8]}: {e}")
    print(f"\n生成 {made} 个 report.html（跳过已存在 {skipped} 个）。"
          f"\n浏览器打开看 → 网络问题就 rm -rf 那个目录 → 重启 run_multi(resume) 补跑。")


if __name__ == "__main__":
    main()
