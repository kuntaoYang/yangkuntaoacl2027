#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_PATH="${MODEL_PATH:-/mnt/usercache/huggingface/Qwen3.5-9B}"
DATA_DIR="${SWE_DATA_DIR:-/mnt/userdata/qwen35_swebench}"
# Nodes are shared, so the conventional 8000 is often taken by another
# container.  Pick a free ephemeral port instead of failing at bind time.
if [ -n "${SGLANG_PORT:-}" ]; then
    PORT="$SGLANG_PORT"
else
    PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
fi
LOG_DIR="$DATA_DIR/logs"
HOST="$(hostname)"

mkdir -p "$LOG_DIR" "$DATA_DIR/outputs" /tmp/qwen35_work
echo "[entrypoint] host=$HOST model=$MODEL_PATH data=$DATA_DIR"

# JIT kernel caches must live on local disk: glusterfs rejects some
# makedirs/rename patterns with ENODATA.
export FLASHINFER_JIT_DIR="${FLASHINFER_JIT_DIR:-/tmp/flashinfer_cache}"
export TRITON_CACHE_DIR="${TRITON_CACHE_DIR:-/tmp/triton_cache}"
mkdir -p "$FLASHINFER_JIT_DIR" "$TRITON_CACHE_DIR"

python3 -m sglang.launch_server \
    --model-path "$MODEL_PATH" \
    --served-model-name Qwen/Qwen3.5-9B \
    --host 127.0.0.1 --port "$PORT" \
    --tp-size 1 \
    --mem-fraction-static "${MEM_FRACTION:-0.85}" \
    --context-length "${CONTEXT_LENGTH:-131072}" \
    --attention-backend "${ATTN_BACKEND:-triton}" \
    --reasoning-parser qwen3 \
    --tool-call-parser qwen3_coder \
    ${EXTRA_SGLANG_ARGS:-} \
    > "$LOG_DIR/sglang-$HOST.log" 2>&1 &
SERVER_PID=$!

ready=0
for _ in $(seq 1 1800); do
    if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        ready=1
        break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "[entrypoint] sglang exited early"
        tail -n 80 "$LOG_DIR/sglang-$HOST.log" || true
        exit 1
    fi
    sleep 2
done
if [ "$ready" != "1" ]; then
    echo "[entrypoint] sglang did not become healthy"
    tail -n 80 "$LOG_DIR/sglang-$HOST.log" || true
    kill "$SERVER_PID" 2>/dev/null || true
    exit 1
fi
echo "[entrypoint] sglang ready on port $PORT"

export SWE_API_BASE="http://127.0.0.1:$PORT/v1"
export SWE_API_KEY="local"
export SWE_WORK_DIR="${SWE_WORK_DIR:-/tmp/qwen35_work}"
export SWE_DATA_DIR="$DATA_DIR"

set +e
python3 "$SCRIPT_DIR/runner.py" --workers "${WORKERS:-8}" --timeout "${TASK_TIMEOUT:-3600}" "$@"
RC=$?
set -e
echo "[entrypoint] runner exited rc=$RC"
kill "$SERVER_PID" 2>/dev/null || true
exit "$RC"
