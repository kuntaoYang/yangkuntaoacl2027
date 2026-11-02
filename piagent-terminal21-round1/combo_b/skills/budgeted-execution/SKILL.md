---
name: budgeted-execution
description: Use for long, uncertain, build-heavy, search-heavy, install-heavy, reverse-engineering, or multi-step tasks that can easily time out.
---

# Budgeted Execution

Use this skill when the task is large or open-ended.

## Protocol

1. **Define the success contract first**
   - What exact file, command, port, binary, or output will the grader check?
   - What is the shortest command that approximates that check?

2. **Create a 3-stage plan**
   - Stage A: cheap environment facts and constraints
   - Stage B: highest-probability implementation path
   - Stage C: final end-to-end verification

3. **Set a budget**
   - Limit exploratory attempts.
   - After 2 failed attempts on the same path, switch approach.
   - Avoid repeated broad web/archive searches unless there is new evidence.

4. **Prefer narrowing experiments**
   - Run the smallest command that falsifies an assumption.
   - Capture exact stderr/stdout and let it choose the next step.

5. **Checkpoint every 5-10 tool calls**
   - Ask: am I closer to the grader contract, or just generating activity?
   - If not closer, pivot.

6. **Stop conditions**
   - If a dependency/tool is unavailable, verify that with one command and pivot.
   - If a service/build appears done, immediately run the closest real acceptance check.

## Heuristics

- For builds: verify the final binary/library in the exact load/run mode required.
- For servers: test with the exact client protocol, not only process/port existence.
- For reverse engineering: build a tiny oracle and test assumptions before full reimplementation.
- For search/download tasks: test candidate URLs/artifacts quickly; do not sink many turns into one dead source.

## Output discipline

Do not write a triumphant summary until Stage C passes.

If stuck, explicitly report the current blocker and the evidence gathered.
