# Qwen3.5-9B + pi agent on SWE-bench Verified (100 tasks)

用 pi（初始版 piagent）harness 在 SWE-bench Verified 的 100 道题上跑 Qwen3.5-9B，
记录完整原始轨迹、token 消耗、产出的 patch，并用官方 harness 判分。

## 目录结构

```
qwen3.5_pi_swe100/
├── pi/                  # pi agent 源码（TypeScript monorepo，需自行构建）
├── swebench_100/        # 100 道题
│   ├── swebench_100.jsonl      # SWE-bench 标准格式（含 problem_statement / test_patch / FAIL_TO_PASS）
│   ├── swebench_100.parquet
│   ├── instance_ids.txt        # 100 个 instance_id
│   └── split_metadata.json     # 子集来源说明
└── pipeline/            # 跑题与判分脚本
    ├── prepare_tasks.py        # 把 jsonl 转成 runner 需要的 tasks.jsonl
    ├── runner.py               # 并发跑 pi，输出轨迹/usage/patch
    ├── entrypoint.sh           # 参考启动脚本（起 SGLang + 调 runner）
    └── score_results.py        # 官方 SWE-bench harness 判分
```

## 前置条件

- Linux，Python 3.11+
- Node.js >= 22、npm
- Docker（判分阶段需要拉取 `swebench/sweb.eval.x86_64.<instance_id>` 镜像）
- 一个 OpenAI 兼容的推理端点（Qwen3.5-9B）

## 1. 构建 pi

```bash
cd pi
npm ci
npm run build
```

构建产物在 `packages/coding-agent/dist`，命令入口是 `packages/coding-agent/dist/cli.js`。

## 2. 起模型服务

任意 OpenAI Chat Completions 兼容端点均可，例如 SGLang：

```bash
python -m sglang.launch_server \
  --model-path /path/to/Qwen3.5-9B \
  --served-model-name Qwen/Qwen3.5-9B \
  --tp-size 1 \
  --context-length 131072 \
  --attention-backend triton \
  --reasoning-parser qwen3 \
  --tool-call-parser qwen3_coder \
  --port 8000
```

> 实测：该模型在当前 SGLang 版本下 `--tp-size 2` 会导致 chat 输出异常（只吐 1 个 token 或乱码），
> 请使用 TP=1；要多卡提速请起多个副本 + 任务分片。

## 3. 准备任务

```bash
cd pipeline
python prepare_tasks.py \
  --input ../swebench_100/swebench_100.jsonl \
  --output /data/qwen35_swebench/tasks.jsonl
```

## 4. 跑题

```bash
export SWE_DATA_DIR=/data/qwen35_swebench        # 需包含 tasks.jsonl，并存放仓库镜像
export SWE_API_BASE=http://127.0.0.1:8000/v1
export SWE_API_KEY=local
export SWE_WORK_DIR=/tmp/qwen35_work

python runner.py --workers 8 --timeout 3000 --shard 0/1
```

- `--shard i/n`：把题均分给 n 个进程/机器，便于多卡并行
- `--force`：忽略已有结果强制重跑（默认跳过已完成题，支持断点续跑）
- 结果目录：`$SWE_DATA_DIR/outputs/{instances,traces,patches}`
- 每题一个 `Qwen3.5-9B，piagent，NNN.json`，字段包括：
  - `raw_trajectory` / `trajectory`：原始逐事件轨迹
  - `token_usage`：input / cached / output / reasoning / total / requests
  - `patch`：agent 产出的 diff
  - `status`、`runtime`、`instance_id`、`repo`

## 5. 判分

```bash
export SWE_INST_DIR=/data/swebench_instances       # 判分用的 instance 数据
python score_results.py --workers 4 --harness-timeout 1800
```

判分会在官方 `swebench/sweb.eval.x86_64.*` 镜像内应用 `test_patch`，
按 `FAIL_TO_PASS` / `PASS_TO_PASS` 计算每题是否解决，输出汇总 JSON。

## 注意事项

- 100 题取自 SWE-bench Verified（公开数据集）。
- 跑题与判分都不需要特定集群；`entrypoint.sh` 里的路径只是示例，全部可用环境变量覆盖。
- 若某题因网络/镜像问题失败，会记为 `error` 而非 0 分；判分时应把这类题排除或重跑，
  避免把环境问题算成模型能力。
