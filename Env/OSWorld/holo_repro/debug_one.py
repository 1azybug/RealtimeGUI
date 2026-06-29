"""调试单个 OSWorld 任务（串行、实时打印），方便人工 debug 模型。

跑指定的一个任务，控制台实时输出：任务 id/指令/轨迹路径，以及每一步的
note / thought / action / 截图路径；任务结束打印分数与 report.html 路径。

它完全复用 run_holo 的环境与 agent 逻辑（同一套 VM 创建、录制、评分），
只是固定为「单任务 + 串行 + --live」。结果写到 results_debug/（可 --result_dir 改）。

用法（在 osworld conda 环境、Holo-3.1-4B 已部署在 :8002 的前提下）：
  cd Env/OSWorld
  python holo_repro/debug_one.py chrome/f79439ad-3ee8-4f99-a518-0eb60e5652b0

地理敏感的 web 任务要让 VM 走美国代理时，前面加环境变量：
  HOLO_VM_PROXY=http://10.200.0.1:7897 python holo_repro/debug_one.py chrome/<id>

详见 复现_debug_单任务.md。
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import run_holo as RH  # noqa: E402  (sets up sys.path / imports desktop_env, holo_agent)
from openai import OpenAI  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Run ONE OSWorld task with live tracing.")
    ap.add_argument("task", help="domain/example_id，例如 chrome/f79439ad-3ee8-4f99-a518-0eb60e5652b0")
    ap.add_argument("--base_url", default="http://127.0.0.1:8002/v1", help="vLLM 端点")
    ap.add_argument("--prompt", default="v1", choices=sorted(RH.SYSTEM_PROMPTS),
                    help="系统提示词变体（v1=baseline，更贴近官方；v2=behavioral）")
    ap.add_argument("--result_dir", default="results_debug", help="结果根目录")
    ap.add_argument("--max_steps", type=int, default=100)
    ap.add_argument("--keep_report", action="store_true",
                    help="若该任务已有 result.txt，默认会跳过；加此项不影响，仅提示。")
    a = ap.parse_args()

    if "/" not in a.task:
        ap.error("task 必须是 domain/example_id，例如 chrome/<id>")
    domain, example_id = a.task.split("/", 1)

    # 复用 run_holo 的全部默认参数，仅固定 单任务 + 串行 + live。
    argv = [
        "--workers", "1", "--live",
        "--domain", domain, "--example_id", example_id,
        "--base_url", a.base_url, "--prompt", a.prompt,
        "--result_dir", a.result_dir, "--max_steps", str(a.max_steps),
        "--no_recording",  # 调试不需要 mp4；report.html 仍会生成
    ]
    args = RH.parse_args(argv)

    print(f"[debug-one] task={domain}/{example_id}  prompt={a.prompt}  "
          f"endpoint={a.base_url}  result_dir={os.path.abspath(a.result_dir)}", flush=True)
    if os.environ.get("HOLO_VM_PROXY"):
        print(f"[debug-one] VM 走代理: HOLO_VM_PROXY={os.environ['HOLO_VM_PROXY']}", flush=True)
    else:
        print("[debug-one] ⚠️ 未设 HOLO_VM_PROXY：VM 无外网出口（宿主无直连外网）。联网 web 任务会卡在 "
              "about:blank。联网任务请加前缀 HOLO_VM_PROXY=http://10.200.0.1:7897", flush=True)

    client = OpenAI(base_url=a.base_url, api_key=args.api_key)
    env = RH._make_env(args)
    try:
        RH.run_one(args, env, client, domain, example_id)
    finally:
        try:
            env.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
