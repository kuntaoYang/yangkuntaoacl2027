#!/usr/bin/env bash
# Keep the original Harbor command and model settings; select only the harness.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VARIANT="${1:-}"
if [[ -z "$VARIANT" ]]; then
  echo 'Usage: run_variant.sh VARIANT <original Harbor command...>' >&2
  exit 2
fi
shift
case "$VARIANT" in
  h0|combo_b|combo_e|combo_b+combo_e) ;;
  *) echo "Unknown variant: $VARIANT" >&2; exit 2 ;;
esac
if [[ $# -eq 0 ]]; then
  echo "Pass the original Harbor command after the variant name." >&2
  exit 2
fi
export PYTHONPATH="$ROOT/$VARIANT${PYTHONPATH:+:$PYTHONPATH}"
exec "$@"
