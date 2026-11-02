#!/usr/bin/env bash
# Run one round-1 harness against the full Terminal-Bench 2.1 dataset.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VARIANT="${1:?Usage: run_terminalbench.sh VARIANT JOB_NAME [extra Harbor flags...]}"
JOB_NAME="${2:?Usage: run_terminalbench.sh VARIANT JOB_NAME [extra Harbor flags...]}"
shift 2
: "${QWEN_BASE_URL:?Set QWEN_BASE_URL to the Qwen3.5-9B OpenAI-compatible /v1 endpoint}"
: "${OPENAI_API_KEY:?Set OPENAI_API_KEY for the Qwen endpoint; local servers may use a dummy value}"

HARBOR_BIN="${HARBOR_BIN:-harbor}"
HARBOR_ENVIRONMENT="${HARBOR_ENVIRONMENT:-udocker_environment:UdockerEnvironment}"
JOBS_DIR="${JOBS_DIR:-$ROOT/jobs}"
N_CONCURRENT="${N_CONCURRENT:-4}"
RECORDED_ORIGINAL='/fs/fast/u2026001290/RSI-CL/piagent_qwen.py'
if [[ -z "${ORIGINAL_PIAGENT_QWEN_FILE:-}" && -f "$RECORDED_ORIGINAL" ]]; then
  export ORIGINAL_PIAGENT_QWEN_FILE="$RECORDED_ORIGINAL"
fi

exec "$ROOT/run_variant.sh" "$VARIANT" "$HARBOR_BIN" run \
  -d terminal-bench/terminal-bench-2-1 \
  --agent piagent_qwen:QwenPi \
  -m openai/Qwen3.5-9B \
  --base-url "$QWEN_BASE_URL" \
  --api-key-name OPENAI_API_KEY \
  --agent-kwarg version=1.4.0 \
  --agent-kwarg reasoning_effort=high \
  --agent-kwarg model_api=openai-completions \
  --env "$HARBOR_ENVIRONMENT" \
  --env-kwarg auto_mounting=true \
  -k 1 \
  -n "$N_CONCURRENT" \
  --jobs-dir "$JOBS_DIR" \
  --job-name "$JOB_NAME" \
  "$@"
