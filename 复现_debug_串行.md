# 串行调试手册 —— `debug_serial.py`（边跑边看模型）

按顺序**一次跑一个任务**（单 VM、串行、不抢资源），控制台**实时打印**每个任务的
id / 指令 / 轨迹路径，以及模型每一步的 `note / thought / action / 截图路径`。
专为**人工 debug 模型**：你可以一边跑一边盯着它在屏幕上看到什么、想了什么、点了哪。

> 与并行的 `run_multi.py` 区别：那个是多 VM 并行冲分、输出交错；这个**严格串行**、输出干净、可逐步追。
> 评测总流程见 `[复现.md](复现.md)`；网络/geo 修复见 `[CLAUDE.md](CLAUDE.md)`；单任务调试见 `[复现_debug_单任务.md](复现_debug_单任务.md)`。

---

## 0. 前置

```bash
cd /mnt/zhaorunsong/repo/CUA/Env/OSWorld
PYO=/mnt/zhaorunsong/anaconda3/envs/osworld/bin/python
```

**(a) 起模型服务 vLLM（至少一个端点 :8002）。** 调试用单卡单实例即可（避开 GPU0）：

```bash
CUDA_VISIBLE_DEVICES=1 PATH="/mnt/zhaorunsong/anaconda3/envs/vllm_Holo/bin:$PATH" \
  /mnt/zhaorunsong/anaconda3/envs/vllm_Holo/bin/python \
  -m vllm.entrypoints.openai.api_server \
  --model /mnt/zhaorunsong/models/Hcompany/Holo-3.1-4B --served-model-name Holo-3.1-4B \
  --tensor-parallel-size 1 --dtype bfloat16 --max-model-len 65536 --max-num-seqs 32 \
  --gpu-memory-utilization 0.90 --limit-mm-per-prompt '{"image": 5}' \
  --trust-remote-code --host 0.0.0.0 --port 8002 &
# 等它打印 "Uvicorn running on ... :8002" 再开跑。细节见记忆 holo-vllm-deploy。
```

```bash
nohup env CUDA_VISIBLE_DEVICES=1 PATH="/mnt/zhaorunsong/anaconda3/envs/vllm_Holo/bin:$PATH" \
  /mnt/zhaorunsong/anaconda3/envs/vllm_Holo/bin/python \
  -m vllm.entrypoints.openai.api_server \
  --model /mnt/zhaorunsong/models/Hcompany/Holo-3.1-4B --served-model-name Holo-3.1-4B \
  --tensor-parallel-size 1 --dtype bfloat16 --max-model-len 65536 --max-num-seqs 32 \
  --gpu-memory-utilization 0.90 --limit-mm-per-prompt '{"image": 5}' \
  --trust-remote-code --host 0.0.0.0 --port 8002 \
  > /mnt/zhaorunsong/repo/CUA/vllm_holo4b.log 2>&1 &
```


> ⚠️ 那个 `PATH="<env>/bin:$PATH"` 必须带：vLLM 的 FlashInfer 采样器 / torch.compile 会 JIT 现编译
> CUDA kernel，子进程要在 PATH 上找到 `ninja`。直接调环境绝对路径 python（未 `conda activate`）时
> PATH 里没有该环境的 bin → 报 `FileNotFoundError: 'ninja'` 启动失败。
> 备选：不加 PATH，改加 `VLLM_USE_FLASHINFER_SAMPLER=0` 走原生 PyTorch 采样（零编译依赖，质量相同）。
> 验证：`curl -s http://127.0.0.1:8002/v1/models | head -c 200`（能列出 Holo-3.1-4B 即可）。

**(b) docker 可用、KVM 开**（OSWorld 用 docker 跑 VM）。脚本内部已 `OSWORLD_FORCE_KVM` 由 run_holo 处理，
你只需保证 docker 正常：`docker ps` 不报错。

**(c) 联网的 web 任务（chrome / multi_apps 等）必须带 `HOLO_VM_PROXY`。** 这台**宿主没有可用的直连外网**
（校园门户挡），VM 的默认路由 VM→容器→宿主→校园网是**死路**，所以 **VM 唯一的外网出口就是
`10.200.0.1:7897`（美国代理）**：

- 家用主机的 SSH 反向隧道已把 `10.200.0.1:7897` 绑好（见 `[CLAUDE.md](CLAUDE.md)` / 记忆 `network-proxy-setup`）；
- 跑命令前加 `HOLO_VM_PROXY=http://10.200.0.1:7897`（见下）。**不带它，任何要联网的页面都加载不出来、卡在
  `about:blank`**——这不是模型问题，也不是 geo 问题，而是 VM 根本没有外网。
- 只有**纯离线任务**（os / vlc / gimp / libreoffice 等不联网的）才可以不带 `HOLO_VM_PROXY`。
- 顺带也修了 geo：带上它后地理敏感任务（航班/酒店/购物）自动出美国。

---



## 1. 跑

```bash
# 串行跑全部 369（默认 test_all.json）
HOLO_VM_PROXY=http://10.200.0.1:7897 $PYO holo_repro/debug_serial.py

# 只跑某个域
$PYO holo_repro/debug_serial.py --domain chrome

# 只跑某域前 N 个（快速试）
$PYO holo_repro/debug_serial.py --domain os --max_tasks 3
$PYO holo_repro/debug_serial.py --domain chrome --max_tasks 3

# 地理敏感 web：让 VM 走美国代理
HOLO_VM_PROXY=http://10.200.0.1:7897 $PYO holo_repro/debug_serial.py --domain chrome
```

注意出现网络问题,可能是没有带`HOLO_VM_PROXY=http://10.200.0.1:7897`

常用参数：


| 参数             | 默认              | 说明                                                                                                               |
| -------------- | --------------- | ---------------------------------------------------------------------------------------------------------------- |
| `--domain`     | `all`           | 单个域或 `all`。域名即 `evaluation_examples/examples/` 下的目录名（chrome / os / vlc / gimp / libreoffice_calc / multi_apps …） |
| `--max_tasks`  | `0`             | 0=不限；>0 取前 N 个                                                                                                   |
| `--prompt`     | `v1`            | 提示词变体：`v1`=baseline（贴近官方），`v2`=behavioral                                                                        |
| `--base_url`   | `:8002/v1`      | vLLM 端点                                                                                                          |
| `--result_dir` | `results_debug` | 结果根目录                                                                                                            |
| `--max_steps`  | `100`           | 单任务最大步数                                                                                                          |


可选环境变量：

- `HOLO_VM_PROXY=http://10.200.0.1:7897` —— VM 的 Chrome 走美国代理（geo 修复）。
- `HOLO_NET_GATE=1` —— 每任务开跑前探网、断网就暂停不计分、全程监控（隧道会闪断时建议开；调试稳定网络可不开）。

---



## 2. 实时输出长什么样

每个任务先打印一个头：

```
==============================================================================
TASK   chrome/f79439ad-3ee8-4f99-a518-0eb60e5652b0
GOAL   Search for a one way flight from Dublin to Vienna on 10th next month for 2 adults.
DIR    /mnt/.../results_debug/pyautogui/screenshot/Holo-3.1-4B/chrome/f79439ad-...
TRAJ   /mnt/.../f79439ad-.../traj.jsonl
SHOTS  /mnt/.../f79439ad-.../step_*.png
REPORT /mnt/.../f79439ad-.../report.html   (任务结束后生成)
==============================================================================
```

然后每一步实时刷：

```
── step 3 ───────────────────────────────────────────────
  note    : flight search form is loaded
  thought : Click the Departure field to enter Dublin
  action  : click(element='Departure input', x=245, y=300)
  shot    : /mnt/.../f79439ad-.../step_3.png
```

任务结束：

```
RESULT chrome/f79439ad-... = 1.00  ✅ PASS   (12 steps, finished_by_agent=True)
REPORT /mnt/.../f79439ad-.../report.html
```

> `action` 里就是模型选的工具与参数（如 `wait(seconds=20)`、`write(content='Dublin', press_enter=True)`），
> 一眼能看出它「想点哪、点了哪」。配合 `shot` 路径的截图，定位是模型问题还是环境问题。

---



## 3. 产物在哪（用于 debug）

每个任务目录 `results_debug/pyautogui/screenshot/Holo-3.1-4B/<domain>/<id>/`：


| 文件                  | 内容                                                      |
| ------------------- | ------------------------------------------------------- |
| `traj.jsonl`        | 逐步轨迹（每行一个 step：note/thought/tool_call/观察等）              |
| `step_*.png`        | 每步的观察截图                                                 |
| `report.html`       | **可视化回放**（截图 + 橙色准星标出点击处 + note/thought/action），浏览器直接打开 |
| `result.txt`        | 0/1 分（有它=这格「已完成」）                                       |
| `meta.json`         | 分数 / prompt 变体 / 是否官方不可行 / 网络状态 等                       |
| `system_prompt.txt` | 这次喂给模型的完整系统提示词（含工具 schema）                              |


---



## 4. 续跑 / 重跑

- **续跑**：脚本看到 `result.txt` 就跳过该任务。中断后再跑同命令即从断点继续。
- **重跑某任务**：删它的目录再跑，例如
  ```bash
  rm -rf results_debug/pyautogui/screenshot/Holo-3.1-4B/chrome/f79439ad-3ee8-4f99-a518-0eb60e5652b0
  $PYO holo_repro/debug_serial.py --domain chrome
  ```
- **全部重来**：`rm -rf results_debug` 再跑。

---



## 5. 单独调一个任务？

用 `[复现_debug_单任务.md](复现_debug_单任务.md)` / `debug_one.py`，直接传 `domain/id` 跑那一个。