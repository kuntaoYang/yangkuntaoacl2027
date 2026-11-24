# piagent_h1 — evidence-loop harness on top of Pi 1.4.0

Self-contained agent harness. `vendor/pi/` is the complete prebuilt Pi 1.4.0
bundle (no `node_modules` needed), `extension.mjs` adds the H1 evidence loop.

- **H0** = stock Pi (the same bundle, no extension) → this is the original piagent
- **H1** = stock Pi + `extension.mjs` (`verify_task` tool, evidence ledger,
  revision-aware validation)

Both arms run the identical `vendor/pi` bytes, so a H0/H1 comparison differs
only by the extension.

## Requirements

- Node >= 22 (`--node /path/to/node` or `PI_NODE=...`)
- Python 3.10+ (only for `launch.py` / `run_bench.py`)
- git (for `run_bench.py` checkout of benchmark repositories)
- An OpenAI-compatible model endpoint

## Configure the model

Pi reads `~/.pi/agent/models.json`. `run_bench.py` writes this for you under
`<out>/home/.pi/agent/models.json`. For manual runs, copy the example:

```bash
mkdir -p ~/.pi/agent
cp models.example.json ~/.pi/agent/models.json   # edit baseUrl / apiKey / model id
printf '{"quietStartup":true,"defaultTools":["read","bash","edit","write"]}\n' \
  > ~/.pi/agent/settings.json
```

Fields that must match your server: `baseUrl`, `apiKey`, `models[].id`,
`contextWindow`, and `compat.supportsDeveloperRole` (Qwen chat templates do not
accept the developer role → keep `false`).

## Smoke test

```bash
python launch.py --variant H0 -- --version
python launch.py --variant H1 -- --version     # needs H1_ARTIFACT_DIR (auto-set)
python launch.py --variant H1 --print-command -- -p "say hello"
```

## Run one task interactively

```bash
cd /path/to/repo-checkout
H1_ARTIFACT_DIR=/tmp/h1-artifacts python ../piagent_h1/launch.py --variant H1 -- -p "fix the failing test"
```

## Run a benchmark

`tasks.jsonl` — one JSON object per line:

```json
{"index":"001","instance_id":"django__django-11099","repo":"django/django","base_commit":"<sha>","problem_statement":"..."}
```

```bash
python run_bench.py --tasks tasks.jsonl --out runs/h1 --variant H1 \
    --base-url http://127.0.0.1:8000/v1 --api-key local \
    --model Qwen/Qwen3.5-9B --workers 4 --timeout 3600
```

Useful flags: `--variant H0|H1`, `--shard i/n`, `--force`, `--thinking high`,
`--node`, `--context-window 131072`.

Outputs per task under `--out`:

| path | content |
| --- | --- |
| `<index>_<instance_id>.json` | status, patch, token usage, metadata |
| `traces/<index>.jsonl` | raw Pi JSON-mode trajectory |
| `artifacts/<index>/` | H1 evidence ledger + verification reports |
| `work/<index>/` | repository checkout (patch source) |
| `summary.jsonl` | one line per finished task |

`score` is always `null` / `score_status: "not_graded"` — this runner produces
patches only. Grade them with the official benchmark harness (for SWE-bench see
`../qwen3.5_pi_swe100/pipeline/score_results.py`).

## Notes / limitations

- `launch.py` passes `--no-extensions --no-skills --no-prompt-templates` to keep
  both arms identical. Remove them if your benchmark needs Pi's own skills.
- `--offline` is set so Pi never calls external services on its own; the model
  endpoint is still reached through `models.json`.
- H1 artifacts must live outside the task workspace, otherwise the extension
  refuses to start. `run_bench.py` handles this automatically.
- Local validation (H1 ledger) is diagnostic evidence, not an official score.
