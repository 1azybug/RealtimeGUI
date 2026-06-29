#!/usr/bin/env bash
# 对外服务版 Holo-3.1-4B vLLM 端点（带 API-Key 鉴权，供远程客户端调用）。
#
# 与 serve_vllm.sh（并行 debug 多实例、无鉴权）相互独立：这里只起 1 个实例，
# 带 --api-key 鉴权，默认占用一张独立 GPU 和独立端口，互不干扰。
#
# API-Key 处理：优先用环境变量 HOLO_API_KEY；否则读 $KEY_FILE；都没有则自动生成
# 一个强随机 key 存到 $KEY_FILE（chmod 600）。客户端用 HTTP 头 Authorization: Bearer <key> 访问。
#
# 用法：
#   bash holo_repro/serve_public.sh            # 在 GPU3、端口 8001 起对外服务
#   bash holo_repro/serve_public.sh --gpu 3 --port 8001
#   bash holo_repro/serve_public.sh --host 127.0.0.1   # 只监听本机（配合隧道穿透，最安全）
#   bash holo_repro/serve_public.sh --status   # 查看状态 + 打印当前 api-key
#   bash holo_repro/serve_public.sh --stop     # 停掉对外服务实例
#
# 安全提示：
#   - 默认 --host 0.0.0.0 会监听所有网卡（含校园网 219.216.64.205），
#     校园网内任何人都能扫到该端口；api-key 是唯一防线，请勿泄露 key。
#   - 若用 frp/ssh -R 等隧道做公网穿透，建议改 --host 127.0.0.1，让隧道转发，
#     端口完全不暴露在校园网上，最安全。

set -u

# ---- 可调默认值 ----
ENV_DIR="/mnt/zhaorunsong/anaconda3/envs/vllm_Holo"
MODEL="/mnt/zhaorunsong/models/Hcompany/Holo-3.1-4B"
SERVED="Holo-3.1-4B"
GPU=3
PORT=8001
HOST="0.0.0.0"
MAX_MODEL_LEN=65536
MAX_NUM_SEQS=32
GPU_MEM_UTIL=0.90
LOG_DIR="/mnt/zhaorunsong/repo/CUA/Env/OSWorld/vllm_logs"
READY_TIMEOUT=600

PYBIN="$ENV_DIR/bin/python"
KEY_FILE="$LOG_DIR/holo_api_key.txt"

usage() { sed -n '2,30p' "$0"; exit 0; }

ACTION="start"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gpu) GPU="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --host) HOST="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --max-model-len) MAX_MODEL_LEN="$2"; shift 2;;
    --max-num-seqs) MAX_NUM_SEQS="$2"; shift 2;;
    --stop) ACTION="stop"; shift;;
    --status) ACTION="status"; shift;;
    -h|--help) usage;;
    *) echo "未知参数: $1"; usage;;
  esac
done

mkdir -p "$LOG_DIR"

# ---- 解析 / 生成 API-Key ----
resolve_key() {
  if [[ -n "${HOLO_API_KEY:-}" ]]; then
    API_KEY="$HOLO_API_KEY"
  elif [[ -s "$KEY_FILE" ]]; then
    API_KEY="$(cat "$KEY_FILE")"
  else
    API_KEY="$("$PYBIN" -c "import secrets;print('holo-'+secrets.token_urlsafe(32))")"
    printf '%s' "$API_KEY" > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
  fi
}
resolve_key

# 精确识别本对外实例：靠 --port 区分（避免误杀 debug 实例）。
STOP_PAT="vllm_Holo/bin/[p]ython -m vllm.entrypoints.openai.api_server.*--port $PORT"
port_up() { curl -s --noproxy '*' -m 3 -H "Authorization: Bearer $API_KEY" \
              "http://127.0.0.1:$PORT/v1/models" 2>/dev/null | grep -q "$SERVED"; }

if [[ "$ACTION" == "stop" ]]; then
  echo "停止对外服务实例（端口 $PORT）..."
  pids=$(pgrep -f "$STOP_PAT" 2>/dev/null)
  if [[ -z "$pids" ]]; then echo "没有在跑。"; exit 0; fi
  echo "  PIDs: $pids"; echo "$pids" | xargs -r kill 2>/dev/null
  sleep 5
  pids=$(pgrep -f "$STOP_PAT" 2>/dev/null)
  [[ -n "$pids" ]] && { echo "  强杀残留: $pids"; echo "$pids" | xargs -r kill -9 2>/dev/null; }
  echo "已停止。"; exit 0
fi

if [[ "$ACTION" == "status" ]]; then
  if port_up; then echo "端口 $PORT (GPU $GPU): ✅ ready"; else echo "端口 $PORT (GPU $GPU): ❌ down"; fi
  echo "API-Key: $API_KEY   (存于 $KEY_FILE)"
  exit 0
fi

# ---- start ----
if port_up; then
  echo "端口 $PORT 已在跑，跳过启动。"
else
  log="$LOG_DIR/vllm_public_gpu${GPU}_port${PORT}.log"
  echo "启动对外服务: GPU $GPU -> $HOST:$PORT  (日志 $log)"
  CUDA_VISIBLE_DEVICES="$GPU" \
  PATH="$ENV_DIR/bin:$PATH" \
  no_proxy="localhost,127.0.0.1" NO_PROXY="localhost,127.0.0.1" \
  nohup "$PYBIN" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" --served-model-name "$SERVED" \
    --api-key "$API_KEY" \
    --tensor-parallel-size 1 --dtype bfloat16 \
    --max-model-len "$MAX_MODEL_LEN" --max-num-seqs "$MAX_NUM_SEQS" \
    --gpu-memory-utilization "$GPU_MEM_UTIL" --limit-mm-per-prompt '{"image": 5}' \
    --trust-remote-code --host "$HOST" --port "$PORT" \
    >"$log" 2>&1 &
  echo "  PID: $!"
fi

echo
echo "等待就绪（最多 ${READY_TIMEOUT}s，模型加载~1-2 分钟）..."
waited=0
while ! port_up; do
  sleep 5; waited=$((waited+5))
  if [[ $waited -ge $READY_TIMEOUT ]]; then
    echo "  ❌ 端口 $PORT 超时未就绪，看日志 $LOG_DIR/vllm_public_gpu${GPU}_port${PORT}.log"
    exit 1
  fi
done

LANIP="$(ip -4 addr show 2>/dev/null | grep -oP '(?<=inet\s)219\.\d+(\.\d+){2}' | head -1)"
echo "  ✅ 端口 $PORT 就绪"
echo
echo "==================== 就绪 ===================="
echo "本机访问 : http://127.0.0.1:$PORT/v1"
[[ -n "$LANIP" ]] && echo "校园网内 : http://$LANIP:$PORT/v1   (同校园网客户端可用)"
echo "API-Key  : $API_KEY"
echo
echo "客户端测试（OpenAI 兼容）："
echo "  curl http://127.0.0.1:$PORT/v1/chat/completions \\"
echo "    -H 'Authorization: Bearer $API_KEY' -H 'Content-Type: application/json' \\"
echo "    -d '{\"model\":\"$SERVED\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}'"
echo "停止：bash holo_repro/serve_public.sh --stop"
echo "=============================================="
