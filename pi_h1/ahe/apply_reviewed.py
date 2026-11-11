"""Apply the reviewed GPT-5.4 proposal to an unchanged Pi checkout, once."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ahe"
BASE = ROOT.parent / "pi"
proposal = json.loads((OUT / "proposal_reviewed.json").read_text())
rules = proposal["rules"]
guidelines = proposal["bash_guidelines"]
assert 0 < len(rules) + len(guidelines) <= 8
assert all(isinstance(s, str) and s.strip() for s in rules + guidelines)
tasks = json.loads((OUT / "evidence_index.json").read_text())
slugs = {t["task_slug"] for t in tasks}
for change in proposal["changes"]:
    for key in ("expected_fixes", "at_risk_regressions"):
        assert set(change["predicted_impact"][key]) <= slugs

paths = ["packages/coding-agent/src/core/system-prompt.ts", "packages/coding-agent/src/core/tools/bash.ts"]
before = {p: (BASE / p).read_text() for p in paths}
assert all((ROOT / p).read_text() == before[p] for p in paths), "Expected unchanged baseline"
anchor = '\taddRule("Be concise in your responses");'
assert before[paths[0]].count(anchor) == 1
addition = "\n".join("\taddRule(" + json.dumps(rule, ensure_ascii=False) + ");" for rule in rules)
(ROOT / paths[0]).write_text(before[paths[0]].replace(anchor, addition + "\n" + anchor))
anchor = '\tguidelines: ["You can inspect PI_* environment variables for current model and session details."],'
assert before[paths[1]].count(anchor) == 1
all_guidelines = ["You can inspect PI_* environment variables for current model and session details."] + guidelines
addition = "\tguidelines: [\n" + "\n".join("\t\t" + json.dumps(s, ensure_ascii=False) + "," for s in all_guidelines) + "\n\t],"
(ROOT / paths[1]).write_text(before[paths[1]].replace(anchor, addition))

manifest = {
    "manifest_version": "1.0", "harness_spec_version": "1.0", "iteration": 1,
    "timestamp": datetime.now(timezone.utc).isoformat(), "author": "gpt-5.4 (AHE Pi adapter; reviewed)",
    "changes": proposal["changes"],
    "verification": {"status": "pending", "note": "Static checks are separate; no Qwen/Terminal-Bench h1 rollout has been run."},
}
(ROOT / "HARNESS_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
sources = {}
for relative in ["skills/agentic-harness-engineering/SKILL.md", "agents/evolve_agent/evolve_prompt.md",
                 "skills/agentic-harness-engineering/references/change-manifest-schema.json"]:
    source = ROOT.parent / "agentic-harness-engineering" / relative
    destination = OUT / "methodology" / source.name
    destination.parent.mkdir(exist_ok=True)
    destination.write_bytes(source.read_bytes())
    sources[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
provenance = {
    "base_directory": str(BASE),
    "base_commit": subprocess.check_output(["git", "-C", str(BASE), "rev-parse", "HEAD"], text=True).strip(),
    "ahe_commit": subprocess.check_output(["git", "-C", str(ROOT.parent / "agentic-harness-engineering"), "rev-parse", "HEAD"], text=True).strip(),
    "workflow": "AHE skill + evolve prompt through offline Pi adapter; NOT native NexAU/E2B evolve.py execution",
    "methodology_sha256": sources,
    "target_model": "Qwen3.5-9B", "evolution_model_requested": "gpt-5.4",
    "chat_url": "https://api2.aigcbest.top/v1/chat/completions",
    "baseline": {"tasks": len(tasks), "passed": sum(t["score"] == 1 for t in tasks),
                 "steps": sum(t["step_count"] for t in tasks)},
    "input_policy": "Only current final trajectory_atif and final scores from 1RSI/结果. Existing evolution folders excluded. Every step represented with labeled field truncation.",
    "source_sha256_before": {p: hashlib.sha256(s.encode()).hexdigest() for p, s in before.items()},
}
(OUT / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
print("Applied reviewed proposal; benchmark verification pending.")
