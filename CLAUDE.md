# CUA 项目记忆

## 服务器网络（关键，复现 OSWorld 评测必读）

这台 GPU 服务器（NEU 实验室）出网有**两条路**：
1. **校园网（默认路由）**：直连，出口 = **中国**（`219.216.64.x`，有 web 认证门户）。
2. **反向代理 `http://127.0.0.1:7897`**：→ 家用主机（挂美国 LA 全局 VPN）→ 出口 = **美国洛杉矶**。这是"我们的"代理。
- ⚠️ **`127.0.0.1:7890` 是别人的代理（日本），别用。**

### 宿主侧
- 宿主**没有可用直连外网**（校园门户挡）；联网命令设 `http_proxy=https_proxy=http://127.0.0.1:7897`、`no_proxy=localhost,127.0.0.1`。
- HF 下载、`holo_repro/prefetch_cache.py` 走 7897。
- 验证：`curl -x http://127.0.0.1:7897 http://ip-api.com/json` → United States / Los Angeles。

### VM 侧 + geo 修复（2026-06-27 最终方案，实测 VM 出美国）
- OSWorld 的 VM（docker→qemu，网卡 `enp0s3`=`20.20.20.x`，网关=容器 `20.20.20.1`；容器 `eth0`=`10.200.0.x`，网关=宿主 docker 网桥 `10.200.0.1`）**默认路由走自己的网络=中国 geo**。
- 后果：**地理敏感的网页任务**（航班/酒店/购物，~52 个 `proxy:true`）会显示中国内容/弹窗而失败——**不是模型能力问题**。
- **正解 = SSH 反向隧道直接把 7897 绑到 docker 网桥**（无需任何中继进程）：
  - 家用主机的隧道脚本加第二条转发 `-R 10.200.0.1:7897:127.0.0.1:7897`（除了原来的 `-R 127.0.0.1:7897:...`），服务器 sshd 开 `GatewayPorts clientspecified`。这样 `10.200.0.1:7897` 由 SSH 直供、出美国，VM 能直接够到。详见 [[network-proxy-setup]]。
  - **⚠️ 不要在服务器跑 `proxy_relay.py` 中继**（早期临时方案，已废弃）：家用脚本每次重连 `fuser -k 7897/tcp` 会把它杀掉。
- **代码侧 geo 修复（全门控 `HOLO_VM_PROXY`，不设即上游原版、别人零影响）**：
  - **关键 bug**：`desktop_env/controllers/setup.py:313` 启动 Chrome 时**硬编码** `--proxy-server=http://127.0.0.1:18888`（VM 内 tinyproxy），**覆盖 gsettings**。已改成 `HOLO_VM_PROXY` 下指向 `10.200.0.1:7897` → 这是 Chrome 真正用上代理的关键。
  - `setup.py` `_proxy_setup`（~534 行）加门控分支：设 gsettings/env 代理、**跳过 tinyproxy/apt**。
  - `holo_repro/run_holo.py`：门控 `enable_proxy=bool(HOLO_VM_PROXY)` + 当 HOLO_VM_PROXY 设时强制 `example["proxy"]=True`。
- **跑法**（确认家用隧道已绑网桥后，无需起中继）：
  ```bash
  cd Env/OSWorld
  HOLO_VM_PROXY=http://10.200.0.1:7897 HOLO_NET_GATE=1 python holo_repro/run_multi.py --base_urls ... --workers 14
  ```
  验证：起一个 VM `curl -x http://10.200.0.1:7897 ip-api` 出 US/LA；或跑 chrome 航班任务截图是**美国 Delta（默认 LAX、无中国弹窗）**。

### 网络不稳 → 复现准确性的三层保障
家用 VPN/7897 **会偶尔断**。靠以下机制保证不把断网/环境故障当模型失败：
1. **`HOLO_NET_GATE=1`**（run_holo）：每任务开跑前经 7897 探测网络；断网就**暂停等待、不在断网窗口跑任务**，`net_ok` 记进 `meta.json`。
2. **多采样 best-of-N**（`run_multi.py`：v1/v2 各 3 次、失败升 10 次）：瞬时抖动被抹平。
3. **infra-fail 护栏**（run_holo）：空轨迹（VM 没就绪/0 步）**不计分、续跑重试**，不污染成 0。

### 关键文件
- `Env/OSWorld/holo_repro/`：`run_holo.py`（单 runner）、`run_multi.py`（多采样编排）、`compare_multi.py`（汇总 CSV）、`proxy_relay.py`（宿主中继）、`backfill_meta.py`。
- 结果：`Env/OSWorld/results_multi/summary.csv`、`never_solved.csv`。
- 评测/网络细节见 `复现.md`、`复现_LLM.md`、`复现_debug_plan.md`。

详细历史与踩坑见 `~/.claude/projects/-mnt-zhaorunsong-repo-CUA/memory/` 下的 `network-proxy-setup.md`、`osworld-holo-repro.md`。
