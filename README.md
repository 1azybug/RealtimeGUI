# CUA —— Holo-3.1 Computer-Use Agent / OSWorld 复现

本仓库做两件事：

1. **一个解耦的 Computer-Use Agent 框架**：把「通用 Holo3.1 智能体」和「具体环境」彻底分开，靠一个极薄的契约层 `computer_env` 连接。Agent 不知道任何环境细节，环境也不反向依赖 Agent。
2. **在本机复现 [Holo-3.1-4B](https://huggingface.co/Hcompany/Holo-3.1-4B) 在 [OSWorld-Verified](https://os-world.github.io/)（369 个任务）上的评测结果**，并提供一整套可调试、可回放、可断点续跑的运行器。

> 沟通 / 文档主要为中文。代码注释与标识符为英文，与代码库风格一致。

---

## 1. 架构总览（先理解再操作）

仓库把 **Agent 端**和 **Env 端**平级解耦，依赖**单向无环**：

```
CUA/
  Agent/                         # Agent 端：所有 Holo 相关逻辑（pip 包 holo-agent）
    holo_agent/
      agent.py                   # HoloComputerAgent：通用官方 agent 循环
      tools.py                   # Holo 工具集 TOOLS + 结构化输出 Step{note,thought,tool_call}
      recorder.py                # 通用轨迹记录（traj.jsonl + 观察截图 + system_prompt.txt）
      report.py                  # 把一次轨迹渲染成自包含 HTML 回放（python -m holo_agent.report）
    docs/holo_official/          # Holo 官方文档（动作/输出规范的唯一权威来源）

  Env/                           # Env 端：通用契约 + 具体环境
    computer_env/                # ComputerEnv 抽象 + InputEvent + StepResult（零 Holo 知识，pip 包 computer-env）
    RealtimeGym/                 # 具体环境①：游戏（GameComputerEnv 适配器 + gui_eval.py）
    OSWorld/                     # 具体环境②：桌面
      holo_repro/                # OSWorld 适配 + 运行器（本次复现入口）
        osworld_computer_env.py  # OSWorldComputerEnv：tool_call → pyautogui
        run_holo.py              # 组装层：建 DesktopEnv + 跑 Agent + 评测（支持并行）
        run_multi.py             # 多采样 best-of-N 编排（瞬时网络抖动护栏）
        debug_serial.py          # 串行调试：一次一个任务、逐步实时打印
        debug_parallel.py        # 并行批量：多 VM 同跑、加速实验
        debug_one.py             # 单任务调试：只跑指定的 domain/id
        prefetch_cache.py        # 预下载所有 setup 输入文件到 cache/（离线化）
        compare_multi.py         # 汇总 CSV
```

**依赖方向**：`holo_agent → computer_env`；环境适配器 `→ computer_env`；运行器（组合根）`→ 两者`。
Env 端**永不**反向 import Agent。**加任何功能前，先确定它属于 Agent 端还是 Env 端。**

### Agent 设计要点（对齐 Holo3.1 官方）

- 结构化输出 `Step{note, thought, tool_call}`，`tool_call` 扁平、`tool_name` 为判别字段（见 `Agent/holo_agent/tools.py` 的 `TOOLS`）。
- 坐标 `[0,1000]` 原点左上，按截图实际尺寸缩放回像素；最多保留最近 3 张观察截图。
- 多轮 `<observation>` / `<tool_output>` 对话布局，`enable_thinking=True`，`reasoning_content` 不回填、跨轮记忆走 `note`。
- 终止 / 不可行：统一用 `answer(content)`，infeasible 从文本判定。

---

## 2. 复现：环境准备

### 2.1 前置条件

- 机器：8×RTX3090（24G），大内存（并行跑很多 VM），`/dev/kvm` 存在。
- 模型权重：`/mnt/zhaorunsong/models/Hcompany/Holo-3.1-4B`。
- 两个 conda 环境：
  - `vllm_Holo`（vllm 0.23）——跑 vLLM 服务。
  - `osworld`（python 3.12 + OSWorld 全部依赖）——跑评测。
- docker：本机同时有 rootless 与系统级 root docker，**必须用系统 docker** 才能用 KVM（见 §2.4）。

### 2.2 准备 OSWorld VM 镜像

OSWorld docker provider 需要 `Env/OSWorld/docker_vm_data/Ubuntu.qcow2`（解压后约 24.5 GB）。HF 直连经常断，本机从 NAS 取得：

```bash
rsync -a --partial --inplace --progress \
  NAS:/data/ruanjunhao/zhaorunsong/repo/xlangai/ubuntu_osworld/Ubuntu.qcow2.zip \
  Env/OSWorld/docker_vm_data/
cd Env/OSWorld/docker_vm_data && unzip -o Ubuntu.qcow2.zip
docker pull happysixd/osworld-docker
```

### 2.3 Python 环境

```bash
conda create -y -n osworld python=3.12 && conda activate osworld
conda install -y -c conda-forge "pip>=24" "setuptools>=70" wheel
cd Env/OSWorld && pip install -r requirements.txt
# 安装解耦的两个本地包（editable），两个 conda 环境都装
pip install -e ../../Env              # computer-env
pip install -e ../../Agent --no-deps  # holo-agent（--no-deps 避免误装 PyPI 同名包）
```

> `vllm_Holo` 环境里请用 `python -m pip` 安装（裸 `pip` 会指向 base 的 py3.7）。

### 2.4 系统 docker + KVM（关键）

本机 rootless docker 用不了 KVM（容器 root 映射成普通用户，`/dev/kvm` 不可写）。改用系统级 root docker：

```bash
export DOCKER_HOST=unix:///var/run/docker.sock   # 当前用户在 docker 组，可访问
export OSWORLD_FORCE_KVM=1                        # 容器是 root，能写 /dev/kvm
```

provider 已改：`OSWORLD_FORCE_KVM=1` 时挂 `/dev/kvm`，并总是挂 `/dev/net/tun`（否则端口转发失效、Flask:5000 连不上、VM 永远 not ready）。KVM 下 VM 冷启 ~25s（TCG ~80s+）。

### 2.5 网络（本机最容易踩坑）

本机宿主**没有可用的直连外网**（校园门户挡），一切出网走**反向代理 `http://127.0.0.1:7897`**（家用主机经 SSH 反向隧道供网，出口美国）。

- **宿主侧**：联网命令设 `http_proxy=https_proxy=http://127.0.0.1:7897`、`no_proxy=localhost,127.0.0.1`。验证：`curl -x http://127.0.0.1:7897 http://ip-api.com/json` → United States。
- **HF 文件下载**：很多任务 setup 要从 `huggingface.co` 下输入文件。**经反代直连 huggingface.co，不要用 hf-mirror**（mirror 会把大文件 LFS 重定向到不可达的 xethub CDN，大文件全失败）。可先预下载：`python holo_repro/prefetch_cache.py`。
- **VM 侧（geo 修复）**：VM 默认路由出口在中国，地理敏感的网页任务（航班/酒店/购物）会显示中国内容而失败。SSH 反向隧道把 `10.200.0.1:7897` 绑到 docker 网桥后，跑评测带上 `HOLO_VM_PROXY=http://10.200.0.1:7897`，VM 的 Chrome 即出美国。全程门控 `HOLO_VM_PROXY`：不设即上游原版行为，对他人零影响。

> 详细网络架构与排错见 [`CLAUDE.md`](CLAUDE.md)。

---

## 3. 跑评测

### 3.1 起 vLLM 服务

一键起多个端点（默认 GPU 1/2/3，避开 GPU0，4~7 留给别人）：

```bash
cd Env/OSWorld
bash holo_repro/serve_vllm.sh              # 默认 GPU 1,2,3 → 端口 8002/8003/8004
bash holo_repro/serve_vllm.sh --gpus 0,1,2,3
bash holo_repro/serve_vllm.sh --status     # 看在跑的端点
bash holo_repro/serve_vllm.sh --stop       # 全停
```

脚本已内置 `PATH=<env>/bin`（解决 vLLM JIT 编译找不到 `ninja`）、健康检查、日志（`Env/OSWorld/vllm_logs/`）。验证：`curl -s --noproxy '*' http://127.0.0.1:8002/v1/models | head -c 200`。

### 3.2 全量并行评测

```bash
cd Env/OSWorld
PYO=/mnt/zhaorunsong/anaconda3/envs/osworld/bin/python
DOCKER_HOST=unix:///var/run/docker.sock OSWORLD_FORCE_KVM=1 \
  HOLO_VM_PROXY=http://10.200.0.1:7897 HOLO_NET_GATE=1 \
  $PYO holo_repro/run_holo.py --workers 10 \
  --base_urls http://127.0.0.1:8002/v1,http://127.0.0.1:8003/v1,http://127.0.0.1:8004/v1 \
  > full_eval.log 2>&1 &
```

- 默认 `--max_steps 100`、全 369 任务、**断点续跑**（跳过已有 `result.txt` 的）、每任务自动生成 `report.html`。
- 结果在 `results/pyautogui/screenshot/Holo-3.1-4B/<domain>/<id>/`。

### 3.3 复现准确性的三层保障（网络会闪断）

家用 VPN / 隧道偶尔会断。靠以下机制保证不把环境故障当模型失败：

1. **`HOLO_NET_GATE=1`**：每任务开跑前经 7897 探网，断网就暂停等待、不在断网窗口记 0 分，`net_ok` 记进 `meta.json`。
2. **多采样 best-of-N**（`run_multi.py`）：瞬时抖动被抹平。
3. **infra-fail 护栏**：空轨迹（VM 没就绪 / 0 步）不计分、续跑重试，不污染成 0。

---

## 4. 调试三件套（定位「模型问题」还是「环境问题」）

| 脚本 | 文档 | 用途 |
| --- | --- | --- |
| `debug_serial.py`   | [`复现_debug_串行.md`](复现_debug_串行.md)   | 严格串行一次一个任务，控制台**逐步实时打印** note/thought/action/截图路径，人工边跑边盯模型 |
| `debug_parallel.py` | [`复现_debug_并行.md`](复现_debug_并行.md)   | 多 VM 并行批量跑，加速实验（不逐步打印，逐任务看 report.html） |
| `debug_one.py`      | [`复现_debug_单任务.md`](复现_debug_单任务.md) | 只跑指定的 `domain/id`，反复重跑某个失败任务 |

```bash
PYO=/mnt/zhaorunsong/anaconda3/envs/osworld/bin/python
cd Env/OSWorld

# 串行盯模型（联网任务务必带 HOLO_VM_PROXY）
HOLO_VM_PROXY=http://10.200.0.1:7897 $PYO holo_repro/debug_serial.py --domain chrome --max_tasks 3

# 并行批量（自动发现在跑的 vLLM 端点 + 自动并发）
HOLO_VM_PROXY=http://10.200.0.1:7897 $PYO holo_repro/debug_parallel.py --domain chrome

# 单任务反复调
HOLO_VM_PROXY=http://10.200.0.1:7897 $PYO holo_repro/debug_one.py chrome/e1e75309-3ddb-4d09-92ec-de869c928143
```

> ⚠️ 联网的 web 任务（chrome/multi_apps 等）**必须带** `HOLO_VM_PROXY=http://10.200.0.1:7897`：本机宿主无直连外网，VM 唯一外网出口就是这个美国代理；不带它页面卡在 `about:blank`（不是模型问题）。纯离线任务（os/vlc/gimp/libreoffice）可省。

### 每个任务的产物

落在 `results*/pyautogui/screenshot/Holo-3.1-4B/<domain>/<id>/`：

| 文件 | 内容 |
| --- | --- |
| `traj.jsonl` | 逐步轨迹（每行一个 step：note/thought/tool_call/观察等） |
| `step_*.png` | 每步的观察截图 |
| `report.html` | **可视化回放**：截图 + 橙色准星标出模型点击处 + 每步 note/thought/action，浏览器直接打开 |
| `result.txt` | 0/1 或连续分（有它=这格「已完成」，断点续跑据此跳过） |
| `meta.json` | 分数 / prompt 变体 / 是否官方不可行 / 网络状态 |
| `system_prompt.txt` | 这次喂给模型的完整系统提示词（含工具 schema） |

---

## 5. 当前结果与诊断

- **官方目标**：Holo-3.1-4B @ OSWorld = **75.8%**（hcompany.ai/holo3.1 原始结果表）。
- **当前复现**：均分 **~0.455**（test_all 369 任务），差官方约 30 点。
- **诊断状态：仍在进行，结论未定。** 当前工作是**先排除网络 / 环境 / 权限等影响因素**，再谈模型能力，**不下「差距主因是模型」这类绝对结论**。仍待排除的环境侧因素包括：网络（VM geo/代理是否每任务真生效、setup 下载与评测期 getter 是否偶发失败被记成 0）、评测器在慢代理下的假阴性（见下文评测器修复，已修一批但可能还有隐藏的）、权限类任务是否因环境配置而非模型失败、需登录的 Google Drive 任务、以及 harness/system prompt/工具集是否与官方一致。方法上逐任务用 `report.html` 把「环境/权限失败」与「模型失败」分清后再统计真实分布；同时与官方 harness / system prompt 对齐（官方未公布 prompt，正在做 v1/v2 提示词 A/B）。

### 评测器 infra 修复（慢代理假阴性）

OSWorld 部分评测器 getter 用 Playwright `networkidle`（要求网络静默 500ms），经慢代理打开内容多的页面时 60s 内永远凑不齐 networkidle → 抓不到参考内容 → 写空文件 → 该任务必判 0。**这是评测器在慢代理下的脆弱点，不是模型问题。** 已在 `desktop_env/evaluators/getters/chrome.py` 把全部 7 处统一改为优雅降级 `_WAIT_PLAN`（`networkidle 30s → load 180s → domcontentloaded 60s`），快网络下行为不变。

> 整改原则：评测器**因环境无法正常运行**才修（只动「怎么等加载」，不碰判什么/阈值/expected，快网络零影响）；评测器**正常运行只是不完美**就不动，以保持与官方 75.8% 可比。详见 [`复现_debug_评测器修复.md`](复现_debug_评测器修复.md)。

---

## 6. 停止评测（务必干净）

`pkill -f run_holo.py` **只杀主进程，杀不到 spawn 出的 worker 子进程**（孤儿继续跑、污染结果）。必须：

```bash
pkill -9 -f "holo_repro/run_holo.py"; pkill -9 -f 'debug_parallel[.]py'
for p in $(ps -eo pid,cmd|awk '/envs\/osworld\/bin\/python -c/ && /multiprocessing.spawn/{print $1}'); do kill -9 $p; done
DOCKER_HOST=unix:///var/run/docker.sock docker ps -aq --filter ancestor=happysixd/osworld-docker | xargs -r docker rm -f
```

> 按 `envs/osworld` 路径过滤，别误杀同机其他用户的 multiprocessing.spawn 进程。

---

## 7. 文档索引

| 文档 | 内容 |
| --- | --- |
| [`CLAUDE.md`](CLAUDE.md) | 项目记忆：服务器网络（反代/隧道/geo 修复）、关键文件 |
| [`复现.md`](复现.md) | 面向人类的完整复现步骤与踩坑 |
| [`复现_LLM.md`](复现_LLM.md) | 面向 AI 代理的复现手册（命令更密、含故障自愈 playbook） |
| [`复现_debug_串行.md`](复现_debug_串行.md) / [`并行`](复现_debug_并行.md) / [`单任务`](复现_debug_单任务.md) | 三套调试运行器手册 |
| [`复现_debug_plan.md`](复现_debug_plan.md) | 低分 debug 规划与诊断 |
| [`复现_debug_评测器修复.md`](复现_debug_评测器修复.md) | 评测器 networkidle 假阴性的修复正当性 |
| [`复现_作废重跑.md`](复现_作废重跑.md) | 人工判定环境失败、作废重跑的手册 |

---

## 致谢

- [OSWorld](https://github.com/xlang-ai/OSWorld)（`Env/OSWorld/` 为其 vendor 化副本，含本项目的 geo/网络/评测器修复）。
- [Holo3.1](https://www.hcompany.ai/blog/holo-3-1) by H Company（[官方文档](https://hub.hcompany.ai/llms.txt)）。
