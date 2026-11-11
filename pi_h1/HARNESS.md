# Pi harness1 — AHE v1.0

This is a copy of `/home/yangkuntao/ACL/pi` with one evidence-driven harness iteration.
The target model remains Qwen3.5-9B. GPT-5.4 was used only for offline analysis and evolution.

Component mapping:

| AHE component | Pi implementation | h1 change |
| --- | --- | --- |
| System rules | `packages/coding-agent/src/core/system-prompt.ts` | Three additive rules |
| Tool descriptions | `packages/coding-agent/src/core/tools/bash.ts` prompt contribution | Three additive guidelines |
| Tool implementations | `packages/coding-agent/src/core/tools/` | Preserved |
| Middleware / hooks | `packages/coding-agent/src/core/extensions/`, agent session | Preserved |
| Skills | Pi resource loader and configured skill directories | Preserved |
| Sub-agents | Existing extension mechanisms | No new registration |
| Long-term memory | Existing project context/resource mechanisms | No benchmark knowledge added |

The two prompt contributions are already wired into Pi. No separate extension activation is needed.
Custom or forced system-prompt replacements retain their original behavior and bypass default rules.
The existing `exposeSessionEnvironment: false` option suppresses bash prompt guidelines, including h1's additions.
Use the default prompt and default bash tool settings when evaluating this variant.

See `HARNESS_MANIFEST.json` for evidence, hypotheses, and regression controls, and
`ahe/README.md` for the workflow, reproduction, validation, and limitations.
