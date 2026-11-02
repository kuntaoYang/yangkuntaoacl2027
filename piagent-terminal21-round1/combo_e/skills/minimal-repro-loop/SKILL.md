---
name: minimal-repro-loop
description: Use when implementing or fixing code where tests fail, behavior is unclear, or repeated rewrites are happening.
---

# Minimal Repro Loop

When a coding task is failing, do not keep rewriting whole files blindly.

## Loop

1. **Capture the first concrete failure**
   - exact traceback, assertion, residual, wrong output, warning, or mismatch

2. **Create the smallest reproducer you can run quickly**
   - one function call
   - one tiny input
   - one unit-sized command

3. **State the failure hypothesis**
   - interface mismatch
   - shape/type bug
   - wrong cancellation semantics
   - numerical method issue
   - shell quoting / variable expansion bug

4. **Make one bounded change**
   - avoid whole-file rewrites unless the existing approach is proven wrong

5. **Re-run the same reproducer immediately**
   - if it still fails, update the hypothesis
   - if it passes, run the next larger check

6. **Promote to end-to-end validation**
   - only after the minimal reproducer is stable

## Special cases

- Numerical code: always check residual/error metric, not just return shape.
- Async code: check exception propagation, cancellation, and task cleanup explicitly.
- Shell scripts: run with `set -euo pipefail` when practical and echo critical paths/vars.
- Data processing: print row counts / schema / sample mismatches before rewriting outputs.

## Anti-patterns

- Replacing the full file before understanding the first failure.
- Ignoring warnings that point to empty inputs or wrong interfaces.
- Switching to a different implementation without preserving a fast reproducer.

Tight loops beat heroic rewrites.
