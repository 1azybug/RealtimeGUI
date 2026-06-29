# 并行调试/批量手册 —— `debug_parallel.py`（多 VM 同跑，加快实验）

起 **N 个 worker**、每个独占一个 VM/容器，从同一任务队列并行取任务跑，worker round-robin 分到多个
vLLM 端点。和串行版 `debug_serial.py` **同一套机制**（复用 run_holo 的 worker/agent/录制/评分），
区别只在**并发**——用来**快速跑完一批任务**，不是逐步盯模型。

> ⚠️ 并行下**不做逐步实时打印**（N 个 VM 的 step 输出会交错成乱码）。改为：每个任务的开始/结束由
> 日志打印（`[task] … 指令` / `[result] … 分数`），每个任务照常生成 `report.html` 事后回放。
> **要一边跑一边逐步盯模型，用** `[复现_debug_串行.md](复现_debug_串行.md)`**。** 单个任务调试用
> `[复现_debug_单任务.md](复现_debug_单任务.md)`。评测总流程 `[复现.md](复现.md)`；网络/geo `[CLAUDE.md](CLAUDE.md)`。

---

## 0. 前置

```bash
cd /mnt/zhaorunsong/repo/CUA/Env/OSWorld
PYO=/mnt/zhaorunsong/anaconda3/envs/osworld/bin/python
```

**(a) 起 vLLM —— 用** `serve_vllm.sh` **一键起多个端点。** 单端点（`--max-num-seqs 32`）能扛 ~8 并发；
想更快就多起几个（每卡一个）。脚本自动分端口、带 PATH 修复、后台 + 日志、健康检查就绪，最后打印
可直接粘贴的 `--base_urls`：

```bash
bash holo_repro/serve_vllm.sh                 # 默认 GPU 1,2,3 → 端口 8002/8003/8004
bash holo_repro/serve_vllm.sh --gpus 1        # 只起一个（GPU1, 8002）
bash holo_repro/serve_vllm.sh --gpus 0,1,2,3      # 起4个
bash holo_repro/serve_vllm.sh --status        # 看哪些端口在跑
bash holo_repro/serve_vllm.sh --stop          # 全停
```

就绪后**不用粘任何东西**——`debug_parallel.py` 会**自动探测**本机在跑的、服务 `Holo-3.1-4B` 的 vLLM 端点
（扫 8000–8016 的 `/v1/models`，按 model id **精确匹配**，跳过别人的其它模型）。日志在 `Env/OSWorld/vllm_logs/`。

> 脚本默认只用 GPU 1～3（避开 GPU0；4～7 留给别人），已内置 `PATH=<env>/bin`（解决 `ninja` 启动失败）。
> 可调项见脚本头部（`--max-model-len` 等）。验证单端点：`curl -s --noproxy '*' http://127.0.0.1:8002/v1/models | head -c 200`。

**(b) docker 可用、KVM 开**：`docker ps` 不报错即可（`OSWORLD_FORCE_KVM` 由 run_holo 内部处理）。

**(c) 联网 web 任务（chrome/multi_apps 等）必须带** `HOLO_VM_PROXY=http://10.200.0.1:7897`：本机宿主无
直连外网，VM 唯一外网出口是这个美国代理；不带它页面加载不出来、卡 `about:blank`（不是模型问题）。
只有纯离线任务（os/vlc/gimp/libreoffice）可省。详见 `[复现_debug_串行.md](复现_debug_串行.md)` §0(c)。

---



## 1. 跑

```bash
# 起好 vLLM 后，直接跑（自动发现端点 + 自动并发数=端点×4），最常用：
HOLO_VM_PROXY=http://10.200.0.1:7897 $PYO holo_repro/debug_parallel.py --domain chrome

# 想手动指定端点/并发也行（可选）：
HOLO_VM_PROXY=http://10.200.0.1:7897 $PYO holo_repro/debug_parallel.py \
  --base_urls http://127.0.0.1:8002/v1,http://127.0.0.1:8003/v1 --workers 12

# 纯离线域不用代理：
$PYO holo_repro/debug_parallel.py --domain libreoffice_calc
```

常用参数：


| 参数             | 默认              | 说明                                                                          |
| -------------- | --------------- | --------------------------------------------------------------------------- |
| `--workers`    | `0`(自动)         | 并发 worker 数；**每个独占一个 VM（≈4G 内存 / 4 vCPU）**。0=自动按端点数×4。受 vLLM 并发与机器内存/CPU 限制 |
| `--base_urls`  | 空(自动)           | 逗号分隔的 vLLM 端点；**留空=自动探测在跑的 vLLM**。worker round-robin 分配，多端点更快               |
| `--model`      | `Holo-3.1-4B`   | 模型名(=vLLM served-model-name)；自动探测按它精确匹配，请求也用它                               |
| `--domain`     | `all`           | 单个域或 `all`（域名见 `evaluation_examples/examples/` 下目录名）                        |
| `--max_tasks`  | `0`             | 0=不限；>0 取前 N 个                                                              |
| `--prompt`     | `v1`            | `v1`=baseline（贴近官方），`v2`=behavioral                                         |
| `--result_dir` | `results_debug` | 结果根目录（与串行版共用，断点续跑互不冲突）                                                      |
| `--max_steps`  | `100`           | 单任务最大步数                                                                     |
| `--stagger`    | `8`             | 每个 worker 启动间隔秒（错开 VM 开机，避免 docker 启动拥塞）                                    |


可选环境变量：`HOLO_VM_PROXY`（VM 走美国代理）、`HOLO_NET_GATE=1`（每任务探网、断网暂停不计分）。

> 注意网络问题多半是没带 `HOLO_VM_PROXY=http://10.200.0.1:7897`。



### 并发数怎么选（吞吐 vs 资源）

- **瓶颈一般是两头**：① vLLM 并发（一个 `--max-num-seqs 32` 实例够 ~8 worker；要更高并发就多起几个端点）；
② 机器内存/CPU（每个 worker = 一个 qemu VM ≈ 4G 内存、4 vCPU）。
- 经验：**单端点 6~8 worker**；**多端点时总 worker ≈ 端点数 × 3~4**（run_multi 用过 4 端点 × 14 worker）。
- worker 太多会让每个 VM 变慢、step 截图变卡，反而不划算。**只用 GPU 0~~3，4~~7 留给别人。**

---



## 2. 输出长什么样（和串行不同）

并行**不逐步打印**。控制台主要是各 worker 交错的任务级日志：

```
... | holo_repro | [task] chrome/f79439ad-... :: Search for a one way flight ...
... | holo_repro | [task] chrome/7a5a7856-... :: Can you save this webpage to bookmarks ...
... | holo_repro | [result] chrome/f79439ad-... = 1.00 (infeasible_task=False, ...)
...
[debug-parallel] 全部完成。逐任务回放看 report.html ...
DONE. mean score over 50/50 tasks = 0.7400
```

**逐步细节看 report.html**（每个任务都生成）：浏览器打开
`results_debug/pyautogui/screenshot/Holo-3.1-4B/<domain>/<id>/report.html`，
截图 + 橙色准星标出点击处 + 每步 note/thought/action，判断模型问题还是环境问题。

---



## 3. 产物在哪（用于 debug）

每个任务目录 `results_debug/pyautogui/screenshot/Holo-3.1-4B/<domain>/<id>/`（与串行版完全一致）：


| 文件                  | 内容                                               |
| ------------------- | ------------------------------------------------ |
| `traj.jsonl`        | 逐步轨迹（每行一个 step：note/thought/tool_call/观察等）       |
| `step_*.png`        | 每步的观察截图                                          |
| `report.html`       | **可视化回放**（截图 + 准星 + note/thought/action），浏览器直接打开 |
| `result.txt`        | 0/1（或连续分，如 PDF 比对）；有它=这格「已完成」                    |
| `meta.json`         | 分数 / prompt 变体 / 是否官方不可行 / 网络状态 等                |
| `system_prompt.txt` | 这次喂给模型的完整系统提示词（含工具 schema）                       |


汇总：跑完会自动打印 `mean score`；也可随时 `$PYO holo_repro/compare_multi.py`（若用 results_multi 结构）。

---



## 4. 续跑 / 重跑 / 停

- **续跑**：看到 `result.txt` 就跳过该任务。中断后再跑同命令即从断点继续。
- **重跑某任务**：删它的目录再跑：
  ```bash
  rm -rf results_debug/pyautogui/screenshot/Holo-3.1-4B/chrome/<id>
  HOLO_VM_PROXY=http://10.200.0.1:7897 $PYO holo_repro/debug_parallel.py --domain chrome --workers 8
  ```
- **全部重来**：`rm -rf results_debug` 再跑。
- **中途停**：`Ctrl-C` 主进程后，确认 worker 子进程和 VM 容器都清掉（否则残留 qemu 占内存）：
  ```bash
  pkill -f 'debug_parallel[.]py'; pkill -f 'run_holo[.]py'
  DOCKER_HOST=unix:///var/run/docker.sock docker rm -f $(docker ps -q --filter ancestor=happysixd/osworld-docker)
  ```

---



## 5. 串行 / 单任务

- 想**逐步实时盯**某次运行 → 串行 `[复现_debug_串行.md](复现_debug_串行.md)`。
- 想**反复重跑某一个任务** → 单任务 `[复现_debug_单任务.md](复现_debug_单任务.md)`。

