"""并行调试/批量 OSWorld 任务（多 VM 同时跑，加快实验速度）。

和 debug_serial.py 同一套机制（复用 run_holo 的 worker/agent/录制/评分），区别只在
**并发**：起 N 个 worker，每个独占一个 VM/容器，从同一任务队列里取任务并行跑，
worker round-robin 分配到多个 vLLM 端点。

⚠️ 并行下**不做逐步实时打印**（N 个 VM 的 step 输出会交错成乱码）。改为：
  * 每个任务开始/结束由 run_holo 的日志打印（[task] ... 指令 / [result] ... 分数）；
  * 每个任务照常生成 report.html，事后用浏览器逐个回放看（路径见结果目录）。
要一边跑一边逐步盯模型，用串行版 debug_serial.py（见 复现_debug_串行.md）。

结果写到 results_debug/（与串行版共用，互不冲突）；已跑过（有 result.txt）的任务自动跳过（断点续跑）。

用法（osworld conda 环境、Holo-3.1-4B 已部署）：
  cd Env/OSWorld
  # 单端点 8 并发跑 chrome：
  HOLO_VM_PROXY=http://10.200.0.1:7897 python holo_repro/debug_parallel.py --domain chrome --workers 8
  # 多端点（更快，需先起多个 vLLM）：
  HOLO_VM_PROXY=http://10.200.0.1:7897 python holo_repro/debug_parallel.py \
      --base_urls http://127.0.0.1:8002/v1,http://127.0.0.1:8003/v1 --workers 12

详见 复现_debug_并行.md。
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import run_holo as RH  # noqa: E402


def _discover_endpoints(served, lo=8000, hi=8016):
    """自动探测本机正在跑的、**确实在服务 `served` 这个模型**的 vLLM 端点，免得手动粘 --base_urls。
    扫 127.0.0.1:lo..hi 的 /v1/models，解析返回的 model id 列表，**只收 id 精确等于 `served` 的端点**
    （避免扫到同机别人的其它模型服务）。闭着的端口会立即拒连、不耗时。"""
    import json as _json
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 不走 http_proxy
    found = []
    for port in range(lo, hi + 1):
        try:
            with opener.open(f"http://127.0.0.1:{port}/v1/models", timeout=1.5) as r:
                body = r.read().decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001  闭口/超时/非 HTTP 都跳过
            continue
        try:
            ids = [m.get("id") for m in (_json.loads(body).get("data") or [])]
        except Exception:  # noqa: BLE001  能连上但不是 vLLM /v1/models 结构 -> 跳过
            continue
        if served in ids:
            found.append(f"http://127.0.0.1:{port}/v1")
        elif ids:
            print(f"[debug-parallel] 端口 {port} 在跑别的模型 {ids}，跳过（要的是 {served!r}）", flush=True)
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description="Run OSWorld tasks in parallel (N VMs) for speed.")
    ap.add_argument("--test_meta", default="evaluation_examples/test_all.json",
                    help="任务清单 json（{domain: [example_id,...]}）")
    ap.add_argument("--domain", default="all", help="单个域或 'all'")
    ap.add_argument("--max_tasks", type=int, default=0, help="0=不限；>0 取前 N 个")
    ap.add_argument("--workers", type=int, default=0,
                    help="并发 worker 数；每个独占一个 VM（≈4G 内存/4 vCPU）。0=自动(端点数×4)。受 vLLM 并发与内存/CPU 限制")
    ap.add_argument("--base_urls", default="",
                    help="逗号分隔的 vLLM 端点；留空=自动探测本机在跑的 vLLM(serve_vllm.sh 起的)。worker round-robin 分配")
    ap.add_argument("--prompt", default="v1", choices=sorted(RH.SYSTEM_PROMPTS),
                    help="系统提示词变体（v1=baseline，更贴近官方；v2=behavioral）")
    ap.add_argument("--model", default="Holo-3.1-4B",
                    help="模型名(= vLLM 的 served-model-name)。自动探测端点时按它精确匹配，请求也用它")
    ap.add_argument("--result_dir", default="results_debug", help="结果根目录")
    ap.add_argument("--max_steps", type=int, default=100)
    ap.add_argument("--stagger", type=float, default=8.0,
                    help="每个 worker 启动间隔秒（错开 VM 开机，避免 docker 端口/启动拥塞）")
    a = ap.parse_args()

    # 端点：未指定则自动探测在跑的 vLLM（serve_vllm.sh 起的），免得手动粘 --base_urls。
    if a.base_urls.strip():
        base_urls = [u.strip() for u in a.base_urls.split(",") if u.strip()]
    else:
        base_urls = _discover_endpoints(a.model)
        if not base_urls:
            print(f"[debug-parallel] 没探测到在跑的、服务 {a.model!r} 的 vLLM。"
                  f"先起服务：bash holo_repro/serve_vllm.sh", flush=True)
            sys.exit(1)
        print(f"[debug-parallel] 自动发现 {len(base_urls)} 个服务 {a.model!r} 的端点: {base_urls}", flush=True)
    # worker 数：0=自动按端点数×4。
    workers = a.workers if a.workers > 0 else max(1, len(base_urls) * 4)

    # 复用 run_holo 的全部默认参数；并行：不加 --live（逐步打印会交错），保留 report 生成。
    argv = [
        "--workers", str(workers), "--model", a.model,
        "--domain", a.domain, "--test_meta", a.test_meta, "--max_tasks", str(a.max_tasks),
        "--base_urls", ",".join(base_urls), "--prompt", a.prompt,
        "--result_dir", a.result_dir, "--max_steps", str(a.max_steps),
        "--no_recording",  # 调试不需要 mp4；report.html 仍会生成
    ]
    args = RH.parse_args(argv)
    tasks = RH.select_tasks(args)
    pending = [t for t in tasks if not RH._already_done(args, *t)]
    print(f"[debug-parallel] 选中 {len(tasks)} 个任务，待跑 {len(pending)} 个；"
          f"{workers} 个 worker / {len(base_urls)} 个端点 {base_urls}；"
          f"prompt={a.prompt}，result_dir={os.path.abspath(a.result_dir)}", flush=True)
    if os.environ.get("HOLO_VM_PROXY"):
        print(f"[debug-parallel] VM 走代理: HOLO_VM_PROXY={os.environ['HOLO_VM_PROXY']}", flush=True)
    else:
        print("[debug-parallel] ⚠️ 未设 HOLO_VM_PROXY：VM 无外网出口（宿主无直连外网）。联网 web 任务会卡在 "
              "about:blank。联网任务请加前缀 HOLO_VM_PROXY=http://10.200.0.1:7897", flush=True)
    if not pending:
        print("[debug-parallel] 没有待跑任务（都已有 result.txt）。要重跑请删对应目录或换 --result_dir。", flush=True)
        RH.aggregate(args, tasks)
        return

    # 与 run_holo.main 的并行分支一致：spawn N 个 worker，各取队列、各持一个 VM。
    ctx = mp.get_context("spawn")
    task_queue = ctx.Queue()
    for t in pending:
        task_queue.put(t)
    procs = []
    for i in range(workers):
        p = ctx.Process(target=RH.worker_loop,
                        args=(i, base_urls[i % len(base_urls)], task_queue, args), daemon=False)
        p.start()
        procs.append(p)
        time.sleep(a.stagger)  # 错开 VM 开机
    for p in procs:
        p.join()
    RH.aggregate(args, tasks)
    print("[debug-parallel] 全部完成。逐任务回放看 report.html（结果目录下各 <domain>/<id>/report.html）。", flush=True)


if __name__ == "__main__":
    main()
