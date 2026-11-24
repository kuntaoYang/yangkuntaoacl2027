// Pi 1.4.0 H1: revision-aware validation, same-process imports, bounded completion review.
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { EvidenceLedger } from "./ledger.mjs";
import { changedPythonFiles, snapshot } from "./snapshot.mjs";

const root = dirname(fileURLToPath(import.meta.url));
const policy = JSON.parse(readFileSync(join(root, "policy.json"), "utf8"));

function run(python, args, cwd, timeout, signal) {
  return new Promise((done, reject) => {
    const child = spawn(python, args, { cwd, detached: true, env: { ...process.env, PYTHONPATH: "", PYTHONDONTWRITEBYTECODE: "1" } });
    let output = "";
    let killed = false;
    const stop = () => { killed = true; try { process.kill(-child.pid, "SIGKILL"); } catch {} };
    const timer = setTimeout(stop, timeout * 1000);
    process.once("SIGTERM", stop);
    signal?.addEventListener("abort", stop, { once: true });
    for (const stream of [child.stdout, child.stderr]) stream.on("data", b => { output = (output + b.toString()).slice(-100000); });
    child.on("error", error => { clearTimeout(timer); process.removeListener("SIGTERM", stop); signal?.removeEventListener("abort", stop); reject(error); });
    child.on("close", code => { clearTimeout(timer); process.removeListener("SIGTERM", stop); signal?.removeEventListener("abort", stop); done({ code, output, killed }); });
  });
}

export default function h1(pi) {
  let ledger;
  let cwd;
  const pendingBash = new Map();
  const output = process.env.H1_ARTIFACT_DIR;
  if (!output) throw new Error("H1_ARTIFACT_DIR must name an output directory outside the task workspace");
  mkdirSync(output, { recursive: true });
  const save = () => writeFileSync(join(output, "state.json"), JSON.stringify({ policy, ...ledger.status(), checks: ledger.checks }, null, 2));
  pi.on("session_start", (_event, ctx) => {
    cwd = resolve(ctx.cwd);
    if (resolve(output) === cwd || resolve(output).startsWith(cwd + "/")) throw new Error("H1 artifacts must stay outside workspace");
    ledger = new EvidenceLedger(snapshot(cwd), policy.max_completion_reminders);
    save();
  });
  pi.on("before_agent_start", event => {
    event.systemPromptOptions.sections.h1_validation = "Validation protocol: after source changes use verify_task with actual target module names. " +
      "Check the issue scenario and relevant regressions. Existing bash remains available for exploration; import-only and simulated guards do not establish target behavior. " +
      "A failed check remains open until the same check passes. If blocked, report uncertainty rather than claiming success.";
  });
  pi.registerTool({
    name: "verify_task",
    label: "Verify current source",
    description: "Execute actual Python repository tests or an assertion script, record current source revision and runtime imports. " +
      "Use real modified module names. Local accepted execution is not proof of semantic coverage or official resolution.",
    parameters: { type: "object", additionalProperties: false,
      required: ["mode", "args", "modules", "acceptance_criteria", "intent"], properties: {
        mode: { type: "string", enum: ["pytest", "unittest", "django", "script"] },
        args: { type: "array", items: { type: "string" }, minItems: 1 },
        modules: { type: "array", items: { type: "string" }, minItems: 1 },
        acceptance_criteria: { type: "string", minLength: 1 },
        intent: { type: "string", enum: ["issue_scenario", "regression", "both"] },
        python: { type: "string", description: "Python interpreter in the task environment; defaults to python." }
      } },
    async execute(id, params, signal) {
      const before = snapshot(cwd);
      const changedTargets = changedPythonFiles(cwd);
      ledger.observeRevision(before);
      const token = createHash("sha256").update(id).digest("hex").slice(0, 16);
      const requestPath = join(output, token + ".request.json");
      const reportPath = join(output, token + ".report.json");
      writeFileSync(requestPath, JSON.stringify({ workspace: cwd, ...params }));
      let report;
      let execution;
      try {
        execution = await run(params.python || "python", [join(root, "verify.py"), "--request", requestPath, "--report", reportPath], cwd, policy.verification_timeout_seconds, signal);
        report = JSON.parse(readFileSync(reportPath, "utf8"));
      } catch (error) {
        report = { accepted: false, error: String(error), coverage: "not_proven" };
      }
      const after = snapshot(cwd);
      const loadedChangedTargets = (report.modules || []).filter(m => changedTargets.includes(m.path)).map(m => m.path);
      const targetAlignment = changedTargets.length === 0 || loadedChangedTargets.length > 0;
      const key = JSON.stringify([params.mode, params.args, [...params.modules].sort(), params.python || "python"]);
      const record = { id, key, revision: before, sourceStable: before === after,
        changedPythonFiles: changedTargets, loadedChangedTargets, targetAlignment,
        accepted: Boolean(report.accepted && targetAlignment && before === after && execution?.code === 0 && !execution?.killed),
        criteria: params.acceptance_criteria, intent: params.intent, report, execution };
      ledger.record(record);
      ledger.observeRevision(after);
      appendFileSync(join(output, "checks.jsonl"), JSON.stringify(record) + "\n");
      save();
      return { content: [{ type: "text", text: JSON.stringify(record) }], details: { h1Accepted: record.accepted } };
    }
  });
  pi.on("tool_execution_start", event => {
    if (event.toolName === "bash") pendingBash.set(event.toolCallId, event.args.command);
  });
  pi.on("tool_execution_end", event => {
    if (!ledger) return;
    ledger.observeRevision(snapshot(cwd));
    const bash = pendingBash.get(event.toolCallId);
    pendingBash.delete(event.toolCallId);
    if (typeof bash === "string" && /(?:^|[;&|\n])\s*(?:[^\s;&|]*\/)?(?:python\d*(?:\.\d+)*|pytest|tox)\b/.test(bash)) {
      const text = (event.result?.content || []).filter(b => b.type === "text").map(b => b.text).join("\n");
      const failed = event.isError || /Traceback \(most recent call last\)|AssertionError|(?:^|\n)FAILED\s|\b[1-9]\d* failed\b/.test(text);
      const key = "bash:" + bash;
      const positive = !failed && /\b[1-9]\d* passed\b|Ran [1-9]\d* tests?[\s\S]*\bOK\b/.test(text);
      if (failed || (ledger.openFailures.has(key) && positive)) {
        const record = { id: event.toolCallId, key, kind: "observed_bash", revision: ledger.revision,
          accepted: Boolean(positive), feedback: text.slice(-12000), semanticCoverage: "not_proven" };
        ledger.record(record);
        appendFileSync(join(output, "checks.jsonl"), JSON.stringify(record) + "\n");
      }
    }
    save();
  });
  pi.on("agent_before_settle", event => {
    ledger.observeRevision(snapshot(cwd));
    // A final assistant message cannot continue until this hook appends the reminder;
    // Pi recomputes canContinue from the returned entries before starting another turn.
    if (event.outcome !== "completed") { save(); return; }
    const reminder = ledger.nextReminder();
    save();
    if (!reminder) return;
    return { entries: [...event.entries, { type: "custom_message", customType: "h1-validation-review", content: reminder, display: false }], continue: true };
  });
  pi.on("agent_settled", () => { if (ledger) save(); });
}
