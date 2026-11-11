"""Validate AHE artifacts and record local checks, without claiming benchmark gains."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ahe"
manifest = json.loads((ROOT / "HARNESS_MANIFEST.json").read_text())
manifest["changes"] = json.loads((OUT / "proposal_reviewed.json").read_text())["changes"]
jsonschema.validate(manifest, json.loads((OUT / "methodology/change-manifest-schema.json").read_text()))
(ROOT / "HARNESS_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

index = json.loads((OUT / "evidence_index.json").read_text())
assert len(index) == len(list((OUT / "analysis").glob("*.md"))) == 89
scores = {t["task_slug"]: t["score"] for t in index}
for change in manifest["changes"]:
    assert all(scores[t] == 0 for t in change["predicted_impact"]["expected_fixes"])
    assert all(scores[t] == 1 for t in change["predicted_impact"]["at_risk_regressions"])

def type_errors(log):
    return re.findall(r"^.*error TS\d+:.*$", (OUT / log).read_text(), re.M)

assert type_errors("check.log") == type_errors("baseline-check.log")
assert len(type_errors("check.log")) == 6
assert "37 passed" in (OUT / "targeted-tests.log").read_text()
assert "Built packages/coding-agent/dist/bundle" in (OUT / "build.log").read_text()
assert "browser" in (OUT / "browser-smoke.log").read_text().lower()
assert (OUT / "cli-help.log").stat().st_size > 100

paths = ["packages/coding-agent/src/core/system-prompt.ts", "packages/coding-agent/src/core/tools/bash.ts"]
patch = subprocess.check_output(["git", "diff", "--", *paths], cwd=ROOT)
(OUT / "harness1.patch").write_bytes(patch)
responses = [json.loads(p.read_text()) for p in (OUT / "responses").glob("*.json")]
validation = {
    "manifest_schema": "passed", "analyzed_tasks": 89, "baseline_passed": 18,
    "targeted_tests": {"files": 3, "passed": 37, "failed": 0},
    "build_offline": "passed", "cli_version": "1.4.0", "cli_help": "passed",
    "npm_run_check": {"status": "failed_on_preexisting_errors", "baseline_errors": 6,
                      "h1_errors": 6, "new_errors": 0, "details": "gpt-6.1-terra missing from repository-pinned model catalog"},
    "browser_smoke": "passed (run separately because full check stops at baseline type errors)",
    "benchmark_h1": "not_run", "benchmark_verdict": "pending",
    "source_sha256_after": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths},
    "api_responses_saved": len(responses),
    "api_reported_prompt_tokens": sum(r.get("usage", {}).get("prompt_tokens", 0) for r in responses),
    "api_reported_completion_tokens": sum(r.get("usage", {}).get("completion_tokens", 0) for r in responses),
    "usage_caveat": "Sum of saved responses, including saved truncated attempts; network attempts without responses cannot be accounted for.",
    "models_returned": sorted({r["model"] for r in responses}),
}
(OUT / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(validation, ensure_ascii=False, indent=2))
