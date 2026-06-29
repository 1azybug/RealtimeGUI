"""作废(删除)因环境问题失败的结果目录,让续跑重新跑它们。

续跑机制:run_holo 看到 result.txt 就跳过该 (task, prompt, attempt) 单元。删掉它的结果目录
=> 下次 run_multi(resume)会重新跑这一格。本脚本帮你按条件精准挑出要作废的格子。

挑选条件(可叠加;不给条件则什么都不删):
  --net-fail              meta.json 显示网络故障(net_ok==False 或 net_dropped_during==True)
  --since "HH:MM"         任务完成时间(result.txt mtime)在 [since, until] 内
  --until "HH:MM"           —— 你知道某段时间主机网络断了,就用这个窗口作废那段跑的
                          时间可写 "HH:MM"(默认今天)或 "YYYY-MM-DD HH:MM"
  --tasks dom/eid ...     指定具体任务(作废其所有 prompt/attempt 的格子)
  --zero-only             只作废上述里得 0 分的(满分/部分分的不动,避免误删真成功的)
  --dry-run               只预览不删

作废后:重跑 = 重新启动 run_multi(带原来的 env),resume 会把这些缺了 result.txt 的格子补跑。
  HOLO_VM_PROXY=http://10.200.0.1:7897 HOLO_NET_GATE=1 python holo_repro/run_multi.py --base_urls ... --workers 14
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import shutil

MODEL = "Holo-3.1-4B"


def _parse_ts(s: str) -> float:
    s = s.strip()
    today = datetime.date.today()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%H:%M:%S", "%H:%M"):
        try:
            t = datetime.datetime.strptime(s, fmt)
            if "%Y" not in fmt:
                t = t.replace(year=today.year, month=today.month, day=today.day)
            return t.timestamp()
        except ValueError:
            continue
    raise SystemExit(f"无法解析时间: {s!r}（用 HH:MM 或 YYYY-MM-DD HH:MM）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result_dir", default="results_multi")
    ap.add_argument("--net-fail", action="store_true")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--tasks", nargs="*", default=[])
    ap.add_argument("--domains", nargs="*", default=[],
                    help="只在这些域里作废（如 chrome multi_apps）——配 --since 用,避免误删离线任务")
    ap.add_argument("--zero-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not (args.net_fail or args.since or args.until or args.tasks):
        raise SystemExit("没给任何条件 → 不删任何东西。用 --net-fail / --since+--until / --tasks。")

    since = _parse_ts(args.since) if args.since else None
    until = _parse_ts(args.until) if args.until else None
    task_set = set(args.tasks)

    base = os.path.join(args.result_dir, "*", "*", "pyautogui", "screenshot", MODEL, "*", "*")
    hit = []
    for d in sorted(glob.glob(base)):
        rp = os.path.join(d, "result.txt")
        if not os.path.exists(rp):
            continue
        dom = os.path.basename(os.path.dirname(d))
        eid = os.path.basename(d)
        key = f"{dom}/{eid}"

        if args.domains and dom not in args.domains:
            continue

        reasons = []
        # 网络故障标记
        if args.net_fail:
            mp = os.path.join(d, "meta.json")
            if os.path.exists(mp):
                try:
                    m = json.load(open(mp, encoding="utf-8"))
                    if m.get("net_ok") is False or m.get("net_dropped_during") is True:
                        reasons.append("net-fail")
                except (ValueError, OSError):
                    pass
        # 时间窗口
        if since is not None or until is not None:
            mt = os.path.getmtime(rp)
            if (since is None or mt >= since) and (until is None or mt <= until):
                reasons.append("time-window")
        # 指定任务
        if key in task_set:
            reasons.append("task-listed")

        if not reasons:
            continue
        # 只作废 0 分(可选)
        if args.zero_only:
            try:
                if float(open(rp).read().strip()) != 0:
                    continue
            except ValueError:
                pass
        hit.append((d, key, ",".join(reasons)))

    print(f"匹配到 {len(hit)} 个要作废的结果格子" + ("（dry-run，不删）" if args.dry_run else ""))
    for d, key, why in hit:
        rel = d.split("/pyautogui/")[0].split(args.result_dir + "/")[-1]  # prompt/attempt
        print(f"  [{why}] {rel}  {key}")
        if not args.dry_run:
            shutil.rmtree(d, ignore_errors=True)
    if not args.dry_run and hit:
        print(f"\n已删除 {len(hit)} 个 → 重新启动 run_multi(resume)即可补跑它们。")


if __name__ == "__main__":
    main()
