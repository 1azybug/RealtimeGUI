#!/usr/bin/env bash
# 一键起/停 多个 Holo-3.1-4B vLLM 端点（给 debug_parallel.py 并行用）。
#
# 每个指定的 GPU 起一个实例：端口 = BASE_PORT + 序号，日志在 LOG_DIR，后台运行，
# 启动后逐个健康检查（curl /v1/models）直到就绪，最后打印可直接粘贴的 --base_urls 串。
# 只用 GPU 0~3，4~7 留给别人（默认 GPU 列表已排除 0）。
#
# 用法：
#   bash holo_repro/serve_vllm.sh                 # 默认在 GPU 1,2,3 起 3 个，端口 8002/8003/8004
#   bash holo_repro/serve_vllm.sh --gpus 1,2      # 指定 GPU
#   bash holo_repro/serve_vllm.sh --gpus 1 --base-port 8002
#   bash holo_repro/serve_vllm.sh --status        # 看哪些端口在跑
#   bash holo_repro/serve_vllm.sh --stop          # 停掉本环境的所有 Holo vLLM 实例
#
# 关键点：必须把 vllm_Holo 环境的 bin 放进 PATH，否则 vLLM 的 FlashInfer/torch.compile
# 找不到 `ninja` 而启动失败（详见 复现_debug_串行.md §0 / 记忆 holo-vllm-deploy）。

set -u

# ---- 可调默认值 ----
ENV_DIR="/mnt/zhaorunsong/anaconda3/envs/vllm_Holo"
MODEL="/mnt/zhaorunsong/models/Hcompany/Holo-3.1-4B"
SERVED="Holo-3.1-4B"
GPUS="1,2,3"
BASE_PORT=8002
MAX_MODEL_LEN=65536
MAX_NUM_SEQS=32
GPU_MEM_UTIL=0.90
LOG_DIR="/mnt/zhaorunsong/repo/CUA/Env/OSWorld/vllm_logs"
READY_TIMEOUT=600          # 每个端点等就绪的最长秒数

PYBIN="$ENV_DIR/bin/python"
PIDFILE="$LOG_DIR/serve_vllm.pids"
# 精确识别"本环境起的 Holo vLLM"用的 cmdline 模式（bracket 避免 pgrep 自匹配本脚本命令）。
STOP_PAT="vllm_Holo/bin/[p]ython -m vllm.entrypoints.openai.api_server"

usage() { sed -n '2,20p' "$0"; exit 0; }

ACTION="start"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gpus) GPUS="$2"; shift 2;;
    --base-port) BASE_PORT="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --max-model-len) MAX_MODEL_LEN="$2"; shift 2;;
    --max-num-seqs) MAX_NUM_SEQS="$2"; shift 2;;
    --stop) ACTION="stop"; shift;;
    --status) ACTION="status"; shift;;
    -h|--help) usage;;
    *) echo "未知参数: $1"; usage;;
  esac
done

port_up() { curl -s --noproxy '*' -m 3 "http://127.0.0.1:$1/v1/models" 2>/dev/null | grep -q "$SERVED"; }

if [[ "$ACTION" == "stop" ]]; then
  echo "停止本环境的 Holo vLLM 实例..."
  pids=$(pgrep -f "$STOP_PAT" 2>/dev/null)
  if [[ -z "$pids" ]]; then echo "没有在跑的实例。"; rm -f "$PIDFILE"; exit 0; fi
  echo "  PIDs: $pids"
  echo "$pids" | xargs -r kill 2>/dev/null
  sleep 5
  pids=$(pgrep -f "$STOP_PAT" 2>/dev/null)
  [[ -n "$pids" ]] && { echo "  强杀残留: $pids"; echo "$pids" | xargs -r kill -9 2>/dev/null; }
  rm -f "$PIDFILE"
  echo "已停止。"
  exit 0
fi

if [[ "$ACTION" == "status" ]]; then
  IFS=',' read -ra GA <<< "$GPUS"
  for i in "${!GA[@]}"; do
    port=$((BASE_PORT + i))
    if port_up "$port"; then echo "  端口 $port (GPU ${GA[$i]}): ✅ ready"; else echo "  端口 $port (GPU ${GA[$i]}): ❌ down"; fi
  done
  exit 0
fi

# ---- start ----
mkdir -p "$LOG_DIR"
: > "$PIDFILE"
IFS=',' read -ra GA <<< "$GPUS"
echo "在 GPU [$GPUS] 起 ${#GA[@]} 个 vLLM 实例，端口从 $BASE_PORT 起；日志在 $LOG_DIR/"
declare -a URLS
for i in "${!GA[@]}"; do
  gpu="${GA[$i]}"
  port=$((BASE_PORT + i))
  [[ "$gpu" == "0" ]] && echo "  ⚠️ 警告：用到了 GPU0（约定只用 0~3、且 0 常被占）"
  URLS+=("http://127.0.0.1:$port/v1")
  if port_up "$port"; then
    echo "  端口 $port 已在跑，跳过。"
    continue
  fi
  log="$LOG_DIR/vllm_gpu${gpu}_port${port}.log"
  echo "  启动: GPU $gpu -> 端口 $port  (日志 $log)"
  # nohup 会 exec 成 python，故 $! 就是 python 的 PID，记进 pidfile。
  CUDA_VISIBLE_DEVICES="$gpu" \
  PATH="$ENV_DIR/bin:$PATH" \
  no_proxy="localhost,127.0.0.1" NO_PROXY="localhost,127.0.0.1" \
  nohup "$PYBIN" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" --served-model-name "$SERVED" \
    --tensor-parallel-size 1 --dtype bfloat16 \
    --max-model-len "$MAX_MODEL_LEN" --max-num-seqs "$MAX_NUM_SEQS" \
    --gpu-memory-utilization "$GPU_MEM_UTIL" --limit-mm-per-prompt '{"image": 5}' \
    --trust-remote-code --host 0.0.0.0 --port "$port" \
    >"$log" 2>&1 &
  echo "$!" >> "$PIDFILE"
done

echo
echo "等待就绪（每个最多 ${READY_TIMEOUT}s，模型加载~1-2 分钟）..."
all_ok=1
for i in "${!GA[@]}"; do
  port=$((BASE_PORT + i))
  waited=0
  while ! port_up "$port"; do
    sleep 5; waited=$((waited+5))
    if [[ $waited -ge $READY_TIMEOUT ]]; then
      echo "  ❌ 端口 $port 超时未就绪，看日志 $LOG_DIR/vllm_gpu${GA[$i]}_port${port}.log"
      all_ok=0; break
    fi
  done
  port_up "$port" && echo "  ✅ 端口 $port 就绪"
done

echo
joined=$(IFS=,; echo "${URLS[*]}")
echo "==================== 就绪 ===================="
echo "端点: $joined"
echo "直接跑即可（debug_parallel.py 会自动发现这些端点，无需手动指定）："
echo "  HOLO_VM_PROXY=http://10.200.0.1:7897 \$PYO holo_repro/debug_parallel.py --domain chrome"
echo "停止全部：bash holo_repro/serve_vllm.sh --stop"
echo "=============================================="
[[ $all_ok -eq 1 ]] || { echo "（有端点未就绪，先排查再跑）"; exit 1; }
