# 复现 Holo-3.1-4B @ OSWorld-Verified — LLM 操作手册

面向 AI 代理。目标：在本机跑完 OSWorld-Verified（369 任务）评 Holo-3.1-4B，产出
`results/.../result.txt`(0/1) 与总均分。**严格按步骤 + 校验点执行；遇异常查 §TROUBLESHOOT。**
人类版见 [`复现.md`](复现.md)。

## CONSTANTS（路径/配置，照抄）
```
REPO        = /mnt/zhaorunsong/repo/CUA
MODEL       = /mnt/zhaorunsong/models/Hcompany/Holo-3.1-4B
OSW         = $REPO/Env/OSWorld
PY_OSWORLD  = /mnt/zhaorunsong/anaconda3/envs/osworld/bin/python
PY_VLLM     = /mnt/zhaorunsong/anaconda3/envs/vllm_Holo/bin/python
QCOW2       = $OSW/docker_vm_data/Ubuntu.qcow2   # 24460197888 bytes
DOCKER_IMG  = happysixd/osworld-docker
CLASH       = http://127.0.0.1:7897
# 评测/服务进程必须用绝对路径 python；vllm_Holo 裸 pip 会指向 base(py3.7)，要用 $PY_VLLM -m pip
```

## CANONICAL RUNTIME ENV（跑评测时这一套，缺一不可）
```bash
DOCKER_HOST=unix:///var/run/docker.sock   # 系统 root docker（KVM 必需）
OSWORLD_FORCE_KVM=1                        # 强制挂 /dev/kvm
http_proxy=$CLASH  https_proxy=$CLASH      # HF 经 clash 直连 huggingface.co 出网（大小文件都行）
no_proxy=localhost,127.0.0.1               # vLLM/docker/VM 直连
# 不要设 OSWORLD_HF_MIRROR！hf-mirror 把大文件(LFS)302→不可达的 cas-bridge.xethub.hf.co，大文件全失败。
# run_holo 的"huggingface→mirror 全局补丁"由 OSWORLD_HF_MIRROR 开关控制，不设即关闭，请求直奔 huggingface.co 经 clash。
```

## 决策点（按现状选）
- KVM：本机 rootless docker 用不了 KVM → **必须** `DOCKER_HOST=系统docker + OSWORLD_FORCE_KVM=1`。验证：容器内 `test -w /dev/kvm`（系统docker 下为真）。
- HF 下载：`huggingface.co` 宿主直连不通（校园网墙）。**用 clash 代理直连 huggingface.co**（clash 节点独立于校园 ipgw，能跟随 LFS/xethub 重定向、大小文件都行）。**不要用 hf-mirror**（大文件失败）。
- 并行：用 `--workers N --base_urls <N个或更少>`（多进程 spawn，每 worker 独立 VM）。N=10 配 5 个 4B 服务实测可行。

## STEP 1 — 资产就位（校验）
```bash
ls -l $QCOW2                      # 须 24460197888 字节
docker images | grep osworld      # happysixd/osworld-docker 在
$PY_OSWORLD -c "import desktop_env, computer_env, holo_agent; print('imports ok')"
```
缺 qcow2：从 NAS `rsync NAS:/data/ruanjunhao/zhaorunsong/repo/xlangai/ubuntu_osworld/Ubuntu.qcow2.zip` 再 unzip 到 `$OSW/docker_vm_data/`。
缺包：`$PY_OSWORLD -m pip install -e $REPO/Env` 和 `-e $REPO/Agent --no-deps`。

## STEP 2 — 网络
```bash
bash /mnt/zhaorunsong/lx/clash/network_login.sh   # 期望 {"res":true,...login_ok}；E2616=欠费→报告人类充值
https_proxy=$CLASH curl -s -o /dev/null -w '%{http_code}\n' --max-time 12 https://hf-mirror.com   # 期望 200/302
```
保活（长跑期间，每 25min 重登）：
```bash
nohup bash -c 'while true; do bash /mnt/zhaorunsong/lx/clash/network_login.sh >/dev/null 2>&1; sleep 1500; done' >/dev/null 2>&1 &
```

## STEP 3 — 预下载 setup 文件到 cache（推荐，减少运行时联网）
```bash
cd $OSW && https_proxy=$CLASH http_proxy=$CLASH $PY_OSWORLD holo_repro/prefetch_cache.py
# 期望末行 downloaded/skipped 多、errors 少；少量 gimp 大图可能失败（运行时 clash 兜底）
```

## STEP 4 — 起 5 个 4B vLLM 服务（GPU 1/2/3/5/7 → 8002-8006）
```bash
ENV=/mnt/zhaorunsong/anaconda3/envs/vllm_Holo
nvidia-smi --query-gpu=index,memory.used --format=csv,noheader   # 选空闲 GPU，避开他人/GPU0
for gp in "1 8002" "2 8003" "3 8004" "5 8005" "7 8006"; do set -- $gp
  nohup env CUDA_VISIBLE_DEVICES=$1 PATH="$ENV/bin:$PATH" no_proxy=localhost,127.0.0.1 \
   $ENV/bin/python -m vllm.entrypoints.openai.api_server --model $MODEL --served-model-name Holo-3.1-4B \
   --tensor-parallel-size 1 --dtype bfloat16 --max-model-len 32768 --max-num-seqs 32 \
   --gpu-memory-utilization 0.90 --limit-mm-per-prompt '{"image": 5}' --trust-remote-code \
   --host 0.0.0.0 --port $2 > $REPO/vllm_4b_$2.log 2>&1 & done
# 等就绪：每个端口 curl -s 127.0.0.1:$port/v1/models 返回 200（约 1-2 分钟）
```

## STEP 5 — 跑评测（断点续跑、并行、自动出 report.html）
```bash
cd $OSW
URLS="http://127.0.0.1:8002/v1,http://127.0.0.1:8003/v1,http://127.0.0.1:8004/v1,http://127.0.0.1:8005/v1,http://127.0.0.1:8006/v1"
nohup env DOCKER_HOST=unix:///var/run/docker.sock OSWORLD_FORCE_KVM=1 \
  http_proxy=$CLASH https_proxy=$CLASH no_proxy=localhost,127.0.0.1 NO_PROXY=localhost,127.0.0.1 \
  $PY_OSWORLD holo_repro/run_holo.py --workers 10 --base_urls "$URLS" \
  > $REPO/full_eval.log 2>&1 &
# 不设 OSWORLD_HF_MIRROR（见 CANONICAL ENV 说明）：HF 经 clash 直连 huggingface.co
```
默认 max_steps=100、全 369、跳过已有 result.txt。

## STEP 6 — 监控（每 ~30min；grep -c 在本环境会吞输出，用 python 统计）
```bash
cd $OSW && $PY_OSWORLD - <<'PY'
import io,glob,collections
rs=glob.glob("results/**/result.txt",recursive=True); v=[];d=collections.defaultdict(list)
for r in rs:
    try: x=float(open(r).read()); v.append(x); d[r.split('/')[-3]].append(x)
    except: pass
print(f"完成 {len(rs)}/369 均分 {sum(v)/len(v):.3f}" if v else "0")
print({k:f"{sum(x)/len(x):.2f}({len(x)})" for k,x in sorted(d.items())})
to=cr=fa=pe=0
for l in io.open("/mnt/zhaorunsong/repo/CUA/full_eval.log",encoding="utf-8",errors="ignore"):
    to+=("huggingface.co" in l and "timed out" in l); cr+="crashed:" in l; fa+="Failed to download" in l; pe+="ProxyError" in l
print(f"HF超时={to} 崩溃={cr} 下载失败={fa} ProxyError={pe}")
PY
# 容器数(应≈10)：DOCKER_HOST=unix:///var/run/docker.sock docker ps --filter ancestor=happysixd/osworld-docker -q|wc -l
# 服务：for p in 8002 8003 8004 8005 8006; do curl -s -o /dev/null -w "$p:%{http_code} " 127.0.0.1:$p/v1/models; done
```
达 369 → 输出最终各域+总均分，停保活。

## STEP 7 — 停止（务必杀 spawn worker，否则孤儿污染）
```bash
pkill -9 -f "holo_repro/run_holo.py"
for p in $(ps -eo pid,cmd|awk '/envs\/osworld\/bin\/python -c/ && /multiprocessing.spawn/{print $1}'); do kill -9 $p; done
DOCKER_HOST=unix:///var/run/docker.sock docker ps -aq --filter ancestor=happysixd/osworld-docker | xargs -r docker rm -f
# 别误杀他人：只杀 cmdline 含 'envs/osworld/bin/python' 的；lxy 的 vllm084 也用 multiprocessing.spawn
# 停 4B 服务（含持显存的 EngineCore）：
pkill -9 -f "served-model-name Holo-3.1-4B"
for p in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader); do
  readlink -f /proc/$p/exe 2>/dev/null | grep -q vllm_Holo && kill -9 $p; done   # 只杀 vllm_Holo 的 EngineCore
```

## TROUBLESHOOT（症状 → 诊断 → 修）
- **VM never ready / 卡在 Checking ready**：缺 `/dev/net/tun`（provider 已加）或 KVM 退出。查容器日志 `docker logs <cid>`；确认系统docker + FORCE_KVM。
- **`huggingface.co ... timed out` 激增**：HF 没走 clash。确认 `http_proxy=https_proxy=$CLASH` 在 env（评测进程及其 spawn worker 都继承）；`https_proxy=$CLASH curl -sIL -o /dev/null -w '%{http_code}' https://huggingface.co/datasets/xlangai/ubuntu_osworld_file_cache/resolve/main/gimp/045bf3ff-9077-4b86-b483-a1040a949cff/gate.jpeg?download=true` 应 200。**不要改用 hf-mirror**（大文件会失败）。
- **`ProxyError` 激增**：clash 挂了。`https_proxy=$CLASH curl -I https://hf-mirror.com`；clash 不通则等其恢复或换节点（clash 是用户的）。
- **`Failed to download` 且 `宿主 bing=000`**：校园网断/欠费（`network_login.sh` 返回 E2616）→ 报告人类充值；保活会自动重登恢复。
- **崩溃但 HF/Proxy 都 0**：偶发 VM 启动慢/截图空，健壮 agent 已兜（连续 4 次才结束）。少量正常。
- **docker 端口锁 `could not be acquired`**：并行抢锁。provider `LOCK_TIMEOUT` 已=180、worker 错峰 8s；仍频繁则减 workers。
- **结果被污染/旧 worker 没杀干净**：见 STEP 7；换配置后 `rm -rf results` 重跑。
- **rootless docker 无 KVM（216/GROUP）**：别给用户级 docker 服务加组；用系统 docker（CANONICAL ENV）。

## VALIDITY / 低分排查（当前 ~0.44，疑有问题）
- 网络故障窗口完成的任务可能被误判 0 → 网络稳定后清空 `results/` 重跑，或只重跑低分域。
- 逐任务用 `report.html`（观察截图+点击准星+note/thought/tool_call+system_prompt）核对模型行为是否符合预期，是定位问题最快路径：
  `$PY_OSWORLD -m holo_agent.report --task-dir results/pyautogui/screenshot/Holo-3.1-4B/<domain>/<id>`
- 核对是否与官方 agent-loop（`Agent/docs/holo_official/agent-loop.md`）一致：结构化输出 `{note,thought,tool_call}`、坐标[0,1000]→像素、最近3张图、`answer` 终止、reasoning 不回填。
- 检查 `max_steps`/`temperature`/工具集是否与官方一致；`write`→`pyautogui.write` 对非 ASCII 不稳。

## VM 内真实网站任务（chrome 域等）
运行时需 VM 联网（经宿主 NAT → 校园网）。clash 在宿主回环、VM 够不到，**无法离线**；校园网欠费时这类必失败。chrome 域若已完成可忽略。
