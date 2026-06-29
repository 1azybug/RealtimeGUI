"""串行调试 OSWorld 任务（一个 VM、一次一个任务、实时打印），方便人工 debug 模型。

按顺序逐个跑任务（默认 test_all.json 的全部 369 个，可用 --domain / --max_tasks 缩小），
每个任务控制台实时输出：任务 id/指令/轨迹路径，以及每一步的 note/thought/action/截图路径；
任务结束打印分数与 report.html 路径。你可以一边跑一边盯着模型在干什么。

与并行的 run_multi 不同：这里**严格串行**（workers=1），不抢资源、输出不交错，专为 debug。
完全复用 run_holo 的环境与 agent 逻辑，只是固定为「串行 + --live」。
结果写到 results_debug/（可 --result_dir 改）；已跑过（有 result.txt）的任务自动跳过（断点续跑）。

用法（osworld conda 环境、Holo-3.1-4B 已部署在 :8002）：
  cd Env/OSWorld
  python holo_repro/debug_serial.py                          # 串行跑全部 369
  python holo_repro/debug_serial.py --domain chrome          # 只跑 chrome 域
  python holo_repro/debug_serial.py --domain os --max_tasks 3 # 只跑 os 域前 3 个

地理敏感的 web 任务要让 VM 走美国代理时，前面加环境变量：
  HOLO_VM_PROXY=http://10.200.0.1:7897 python holo_repro/debug_serial.py --domain chrome

详见 复现_debug_串行.md。
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import run_holo as RH  # noqa: E402
from openai import OpenAI  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Serially run OSWorld tasks with live tracing.")
    ap.add_argument("--test_meta", default="evaluation_examples/test_all.json",
                    help="任务清单 json（{domain: [example_id,...]}）")
    ap.add_argument("--domain", default="all", help="单个域或 'all'")
    ap.add_argument("--max_tasks", type=int, default=0, help="0=不限；>0 取前 N 个")
    ap.add_argument("--base_url", default="http://127.0.0.1:8002/v1", help="vLLM 端点")
    ap.add_argument("--prompt", default="v1", choices=sorted(RH.SYSTEM_PROMPTS),
                    help="系统提示词变体（v1=baseline，更贴近官方；v2=behavioral）")
    ap.add_argument("--result_dir", default="results_debug", help="结果根目录")
    ap.add_argument("--max_steps", type=int, default=100)
    a = ap.parse_args()

    argv = [
        "--workers", "1", "--live",
        "--domain", a.domain, "--test_meta", a.test_meta, "--max_tasks", str(a.max_tasks),
        "--base_url", a.base_url, "--prompt", a.prompt,
        "--result_dir", a.result_dir, "--max_steps", str(a.max_steps),
        "--no_recording",  # 调试不需要 mp4；report.html 仍会生成
    ]
    args = RH.parse_args(argv)

    tasks = RH.select_tasks(args)
    pending = [t for t in tasks if not RH._already_done(args, *t)]
    print(f"[debug-serial] 选中 {len(tasks)} 个任务，待跑 {len(pending)} 个"
          f"（prompt={a.prompt}，endpoint={a.base_url}，result_dir={os.path.abspath(a.result_dir)}）",
          flush=True)
    if os.environ.get("HOLO_VM_PROXY"):
        print(f"[debug-serial] VM 走代理: HOLO_VM_PROXY={os.environ['HOLO_VM_PROXY']}", flush=True)
    else:
        print("[debug-serial] ⚠️ 未设 HOLO_VM_PROXY：VM 无外网出口（宿主无直连外网）。联网 web 任务会卡在 "
              "about:blank。联网任务请加前缀 HOLO_VM_PROXY=http://10.200.0.1:7897", flush=True)
    if not pending:
        print("[debug-serial] 没有待跑任务（都已有 result.txt）。要重跑请删对应目录或换 --result_dir。", flush=True)
        RH.aggregate(args, tasks)
        return

    client = OpenAI(base_url=a.base_url, api_key=args.api_key)
    env = RH._make_env(args)
    try:
        for i, (domain, example_id) in enumerate(pending, 1):
            print(f"\n>>> 进度 [{i}/{len(pending)}]  {domain}/{example_id}", flush=True)
            try:
                RH.run_one(args, env, client, domain, example_id)
            except Exception as e:  # noqa: BLE001  一个任务崩了不影响后续
                print(f"!!! 任务 {domain}/{example_id} 崩溃: {e}", flush=True)
        RH.aggregate(args, tasks)
    finally:
        try:
            env.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
