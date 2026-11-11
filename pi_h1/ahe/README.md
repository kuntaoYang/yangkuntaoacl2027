# pi_h1 生成说明

输入是 `../Qwen3.5-9b-terminal2.1/1RSI/结果` 的 89 份最终记录，基线通过 18/89（20.22%），共 5,088 个 ATIF steps。
源码基线为 `../pi`，commit `2c8d1feb147f6b3d97e855da803bfe7b19f3c403`，与轨迹记录一致。未使用已有 evolution_round 目录的提案或其他轮次成绩。

本次使用 AHE 仓库自带的 `skills/agentic-harness-engineering/SKILL.md` 和 `agents/evolve_agent/evolve_prompt.md`，通过本目录的离线 Pi 适配器执行“既有评估 → 逐题分析 → 演化提案 → 证据复核 → 修订 → 源码修改”。**没有运行原生 NexAU/E2B 的 evolve.py，也没有运行非开源 Agent Debugger 服务。** 适配器用 GPT-5.4 承担轨迹摘要分析，避免将 Pi 工程改造成 NexAU。

模型请求使用 `gpt-5.4` 和 `https://api2.aigcbest.top/v1/chat/completions`。凭据只通过进程环境传入，未保存。请求、返回的模型名称、usage 和响应正文均可在 `requests/`、`responses/` 审计；返回名称包含 `gpt-5.4` 及其日期版本。

每个 step 都保留在 `input/` 中，长字段保留头尾并标明截断；这些是有损摘要，不代表模型完整阅读了全部 2.7 GB 原始文件。`evidence_index.json` 记录原始文件路径、SHA-256、得分和 step 数。`analysis/` 包含 89 份模型报告。报告是模型判断，可能有误，不能直接视为已证实因果结论。

`proposal.json` 为第一份提案，`proposal_reviewed.json` 是复核后实际采用的提案。复核直接对照了任务 001、003、004、018、019 的关键 step：删除源文件后再读取、把输出管道的成功当作原程序成功、未证明测试实际执行、验证失败后宣称成功、打开恢复数据后关联文件消失。修改仅加入通用规则，任务名称和具体解法不进入运行时提示词。

人工审阅处理：解开模型多包的一层 `proposal`；从运行时规则删除模型附带的 `Evidence:` 任务引用（保留 manifest 证据）；将第一项变更的风险任务换为已通过的构建类对照任务，便于下一轮观测真正的 pass→fail。源码格式由原仓库 Biome 整理。

## 产物

- `../HARNESS_MANIFEST.json`：AHE v1.0 格式变更记录，benchmark verification 为 pending。
- `overview.md`、`analysis/`：汇总和逐题分析。
- `provenance.json`、`evidence_index.json`：源码、方法文件和输入追溯。
- `harness1.patch`：相对原 pi 的运行时源码差异。
- `validation.json`：最终静态检查、测试、构建情况。
- `model-catalog.json`：仓库 Nix 配置固定的官方构建数据快照，SHA-256 为 `7fe1b41feaf43a7aad4bc832e6b306c7ced56e6d41bbc724b74e91eeacff6edf`。

## 使用

需要 Node >=22.19；本次验证使用 Node 24.15.0。使用此目录的构建产物运行，而不是系统中其他已安装的 pi：

```bash
cd /home/yangkuntao/ACL/pi_h1
node packages/coding-agent/dist/bundle/cli.js --help
```

继续沿用原有 Qwen provider/model 和采样配置。下一轮 Terminal-Bench 的安装/打包路径必须指向 **pi_h1**；若评测适配器仍从 npm 安装原版 pi，则不会使用本次修改。此目录不包含新的 Qwen 推理服务或新的 benchmark 成绩。

重建：

```bash
npm ci --ignore-scripts
node packages/ai/scripts/hydrate-model-catalog.ts ahe/model-catalog.json
npm run build:offline
```

复现分析流程（已有响应会复用，不会重复收费）：

```bash
export AHE_API_KEY='<your key>'
python ahe/evolve_pi.py prepare
python ahe/evolve_pi.py analyze
python ahe/evolve_pi.py evolve
python ahe/evolve_pi.py refine
```

`apply_reviewed.py` 只允许向未修改的基线应用一次，防止重复插入规则；现有目录已应用。适配器按本机原始输入目录定位文件，迁移机器需调整 `SOURCE`。提案产生本身不会自动修改源码。

## 验证边界

没有重跑 Qwen3.5-9B 的 Terminal-Bench。expected_fixes 是下一轮待检验的假设，并非已证明能转为通过。保持相同任务、模型和评测配置，比较预测修复任务及已通过对照任务后，再依据 AHE 更新 manifest 的 keep/revert/partial 结论。

原始源码配合仓库固定模型快照时已有 6 个类型检查错误，均为模型目录缺少 `gpt-6.1-terra` 引发的测试类型错误，记录在 `baseline-check.log`。不为消除这些错误更改模型配置或删除原测试；修改后的 `check.log` 用于核对有无新增错误。
