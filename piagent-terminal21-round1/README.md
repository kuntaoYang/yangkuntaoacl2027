# Terminal-Bench 2.1: round 1 Pi Harnesses

Four independent Harbor-compatible harness directories are `h0/`, `combo_b/`,
`combo_e/`, and `combo_b+combo_e/`. Each exports `piagent_qwen:QwenPi`, accepts
the same Harbor agent constructor arguments as the original Pi adapter, and
uses the same Qwen3.5-9B model metadata in all four variants. The sole planned
experimental difference is which Pi skills are registered.

| Variant | Skills |
| --- | --- |
| `h0` | None |
| `combo_b` | `budgeted-execution` |
| `combo_e` | `minimal-repro-loop` |
| `combo_b+combo_e` | Both |

## Run with the original Harbor command

Use the same Harbor 0.25.0 executable, Qwen3.5-9B endpoint, task runtime and
timeout settings used in the original evaluation. The provided runner defaults
to the recorded Terminal-Bench 2.1 dataset, Pi 1.4.0, Qwen model settings and
`udocker_environment:UdockerEnvironment`. That environment module must be on
`PYTHONPATH`, as it was for the original run. Set the endpoint and API-key
environment variables before running; the key is never written into a harness:

```bash
cd /home/yangkuntao/ACL/piagent-terminal21-round1
export QWEN_BASE_URL='http://127.0.0.1:18888/v1'  # replace if endpoint differs
export OPENAI_API_KEY='...'                         # use your endpoint's key
export PYTHONPATH='/path/to/original/udocker/module'  # original runtime module
./run_terminalbench.sh h0 qwen35-tb21-round1-h0
./run_terminalbench.sh combo_b qwen35-tb21-round1-combo-b
./run_terminalbench.sh combo_e qwen35-tb21-round1-combo-e
./run_terminalbench.sh combo_b+combo_e qwen35-tb21-round1-combo-be
```

Run the four commands separately or through your scheduler. Each needs the same
89 tasks and a distinct job name. `JOBS_DIR`, `N_CONCURRENT`, `HARBOR_BIN`, and
`HARBOR_ENVIRONMENT` may be set in the environment. Extra Harbor flags may be
passed after the job name. For an existing original command, use
`./run_variant.sh VARIANT <original Harbor command...>` instead. The launcher
only changes `PYTHONPATH` so Harbor imports the selected `piagent_qwen:QwenPi`.
It does not modify Pi's source or Qwen model weights.

All four wrappers subclass the original QwenPi adapter when its source is
available. Skill files are
installed into the task environment before each Pi run. They are discoverable
by Pi 1.4.0; whether the model chooses to read and follow them remains an
empirical question. The original custom `piagent_qwen.py` source was not
available in this workspace. If it is available during evaluation, set
`ORIGINAL_PIAGENT_QWEN_FILE` to its path: the wrapper verifies the recorded
SHA-256 and subclasses it directly, preserving its model metadata and runtime
behavior. The runner automatically selects the recorded path on the original
cluster when it exists. Otherwise it subclasses official Harbor Pi and
reconstructs model metadata from the run provenance. Re-run `h0` alongside the
other three before comparing results. No variant has yet been scored by
Terminal-Bench.

Source proposals and baseline audit:
`../Qwen3.5-9b-terminal2.1/1RSI/evolution_round_1/`.
