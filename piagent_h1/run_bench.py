#!/usr/bin/env python3
"""Batch runner for piagent_h1.

Runs one task per process invocation of the bundled Pi (H0 = stock, H1 = stock +
the evidence-loop extension) and records trajectory, patch and token usage per
task.  Grading is deliberately not part of this script: run the official
benchmark harness on the produced patches.

Example:
    python run_bench.py --tasks tasks.jsonl --out runs/h1 --variant H1 \
        --base-url http://127.0.0.1:8000/v1 --model Qwen/Qwen3.5-9B \
        --workers 4 --timeout 3600
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent

PROMPT_TEMPLATE = """You are working in a checkout of the GitHub repository {repo}.

Resolve the issue below by editing the repository's source code. Make the smallest
change that fixes the problem.

<issue>
{problem}
</issue>

Rules:
- Modify source files in the current working directory only.
- Use bash to inspect files and run targeted tests when useful.
- Do not commit, do not create branches, do not run git checkout/reset/clean.
- When the fix is complete, stop. The final working tree is the answer.
"""

_log_lock = threading.Lock()


def log(msg: str) -> None:
    with _log_lock:
        print(f"[{time.strftime('%F %T')}] {msg}", flush=True)


def resolve_node(explicit: str | None) -> str:
    rejected = []
    for cand in (explicit, os.environ.get("PI_NODE"), "node"):
        if not cand:
            continue
        path = cand if os.path.isabs(cand) else shutil.which(cand)
        if not path or not os.path.exists(path):
            continue
        try:
            version = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30).stdout
            major = int(version.strip().lstrip("v").split(".")[0])
        except (OSError, ValueError, subprocess.SubprocessError):
            major = 0
        if major >= 22:
            return path
        rejected.append(f"{path} (v{major})")
    detail = f"; found too old: {', '.join(rejected)}" if rejected else ""
    raise SystemExit(f"node >= 22 not found; pass --node /path/to/node{detail}")


def build_models(args) -> dict:
    return {
        "providers": {
            args.provider: {
                "name": "OpenAI-compatible endpoint",
                "baseUrl": args.base_url,
                "apiKey": args.api_key,
                "api": "openai-completions",
                "models": [
                    {
                        "id": args.model,
                        "name": args.model,
                        "reasoning": True,
                        "input": ["text"],
                        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        "contextWindow": args.context_window,
                        "maxTokens": args.max_tokens,
                        "samplingParams": {
                            "temperature": args.temperature,
                            "top_p": args.top_p,
                            "presence_penalty": args.presence_penalty,
                        },
                        "compat": {"supportsDeveloperRole": False},
                    }
                ],
            }
        }
    }


def setup_pi_home(home: Path, models: dict) -> None:
    cfg = home / ".pi" / "agent"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "models.json").write_text(json.dumps(models, indent=2) + "\n", encoding="utf-8")
    (cfg / "settings.json").write_text(
        json.dumps({"quietStartup": True, "defaultTools": ["read", "bash", "edit", "write"]}),
        encoding="utf-8",
    )


def mirror_repo(repo: str, cache: Path) -> Path:
    dest = cache / (repo.replace("/", "__") + ".git")
    if not dest.exists():
        log(f"mirror {repo}")
        subprocess.run(
            ["git", "clone", "--mirror", "--quiet", f"https://github.com/{repo}.git", str(dest)],
            check=True,
            timeout=3600,
        )
    return dest


def prepare_workdir(task: dict, args, cache: Path) -> Path:
    if task.get("workdir"):
        return Path(task["workdir"]).resolve()
    work = args.work_root / task["index"]
    if work.exists():
        shutil.rmtree(work)
    mirror = mirror_repo(task["repo"], cache)
    subprocess.run(
        ["git", "clone", "--quiet", "--shared", "--no-checkout", str(mirror), str(work)],
        check=True,
        timeout=1800,
    )
    subprocess.run(
        ["git", "-C", str(work), "checkout", "--quiet", "--force", task["base_commit"]],
        check=True,
        timeout=600,
    )
    for key, value in (("user.email", "piagent@localhost"), ("user.name", "piagent")):
        subprocess.run(["git", "-C", str(work), "config", key, value], check=False)
    return work


def rev_parse(work: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def make_patch(work: Path, baseline: str) -> str:
    subprocess.run(["git", "-C", str(work), "add", "-A"], check=False, timeout=300)
    return subprocess.run(
        ["git", "-C", str(work), "diff", "--cached", "--binary", "--no-color", baseline],
        capture_output=True, text=True, timeout=600,
    ).stdout


def extract_usage(trace_path: Path) -> dict:
    total = {
        "input_tokens_including_cache": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "requests": 0,
    }
    if not trace_path.exists():
        return total
    with trace_path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("type") != "message_end":
                continue
            msg = obj.get("message") or {}
            if msg.get("role") != "assistant":
                continue
            usage = msg.get("usage") or {}
            total["input_tokens_including_cache"] += int(usage.get("input") or 0)
            total["cached_input_tokens"] += int(usage.get("cacheRead") or 0)
            total["output_tokens"] += int(usage.get("output") or 0)
            total["reasoning_tokens"] += int(usage.get("reasoning") or 0)
            total["total_tokens"] += int(usage.get("totalTokens") or 0)
            total["requests"] += 1
    return total


def pi_command(task: dict, args, node: str, artifact_dir: Path) -> list[str]:
    cmd = [
        node, str(ROOT / "vendor/pi/cli.js"),
        "--no-extensions", "--no-skills", "--no-prompt-templates",
    ]
    if args.variant == "H1":
        cmd += ["-e", str(ROOT / "extension.mjs")]
    prompt = PROMPT_TEMPLATE.format(repo=task["repo"], problem=task["problem_statement"])
    cmd += [
        "--mode", "json",
        "--provider", args.provider,
        "--model", args.model,
        "--thinking", args.thinking,
        "--no-session", "--offline", "-na", "-nc",
        prompt,
    ]
    return cmd


def run_task(task: dict, args, node: str) -> dict:
    idx = task["index"]
    result_path = args.out / f"{idx}_{task['instance_id']}.json"
    if result_path.exists() and not args.force:
        return {"index": idx, "status": "skipped"}

    work = prepare_workdir(task, args, args.mirror_cache)
    baseline = rev_parse(work)
    trace_dir = args.out / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace = trace_dir / f"{idx}.jsonl"
    stderr = trace_dir / f"{idx}.stderr.log"
    artifact_dir = args.out / "artifacts" / idx
    artifact_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["HOME"] = str(args.home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if args.variant == "H1":
        env["H1_ARTIFACT_DIR"] = str(artifact_dir.resolve())
    else:
        env.pop("H1_ARTIFACT_DIR", None)

    cmd = pi_command(task, args, node, artifact_dir)
    started = time.time()
    status = "finished"
    with trace.open("w", encoding="utf-8") as out, stderr.open("w", encoding="utf-8") as err:
        try:
            proc = subprocess.run(cmd, cwd=str(work), env=env, stdout=out, stderr=err,
                                  timeout=args.timeout, text=True)
            if proc.returncode != 0:
                status = "error"
        except subprocess.TimeoutExpired:
            status = "timeout"

    patch = make_patch(work, baseline) if status != "error" else ""
    usage = extract_usage(trace)
    if status == "finished" and usage["total_tokens"] == 0:
        status = "no_model_response"
    record = {
        "model": args.model,
        "harness": "piagent_h1" if args.variant == "H1" else "piagent",
        "variant": args.variant,
        "task_id": idx,
        "instance_id": task["instance_id"],
        "repo": task.get("repo"),
        "base_commit": task.get("base_commit"),
        "status": status,
        "score": None,
        "score_status": "not_graded",
        "token_usage": usage,
        "patch": patch,
        "raw_trajectory_path": str(trace),
        "meta": {
            "variant": args.variant,
            "elapsed_seconds": round(time.time() - started, 1),
            "artifact_dir": str(artifact_dir) if args.variant == "H1" else None,
            "provider": args.provider,
            "thinking": args.thinking,
            "timeout": args.timeout,
        },
    }
    result_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "index": idx,
        "status": status,
        "seconds": record["meta"]["elapsed_seconds"],
        "tokens": usage["total_tokens"],
    }


def load_tasks(path: Path, shard: tuple[int, int] | None) -> list[dict]:
    tasks = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                tasks.append(json.loads(line))
    if shard:
        i, n = shard
        tasks = [t for pos, t in enumerate(tasks) if pos % n == i]
    return tasks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tasks", required=True, help="JSONL with index/instance_id/repo/base_commit/problem_statement")
    ap.add_argument("--out", required=True, help="output directory for results, traces, patches, artifacts")
    ap.add_argument("--variant", choices=["H0", "H1"], default="H1")
    ap.add_argument("--node", default=None)
    ap.add_argument("--base-url", default=os.environ.get("PI_BASE_URL", "http://127.0.0.1:8000/v1"))
    ap.add_argument("--api-key", default=os.environ.get("PI_API_KEY", "local"))
    ap.add_argument("--provider", default=os.environ.get("PI_PROVIDER", "qwen"))
    ap.add_argument("--model", default=os.environ.get("PI_MODEL", "Qwen/Qwen3.5-9B"))
    ap.add_argument("--thinking", default="high")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--shard", default=None, help="i/n, keeps every n-th task starting at i")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--context-window", type=int, default=131072)
    ap.add_argument("--max-tokens", type=int, default=32768)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--presence-penalty", type=float, default=1.5)
    args = ap.parse_args()

    args.out = Path(args.out).resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    args.work_root = args.out / "work"
    args.work_root.mkdir(exist_ok=True)
    args.mirror_cache = args.out / "mirrors"
    args.mirror_cache.mkdir(exist_ok=True)
    args.home = args.out / "home"
    setup_pi_home(args.home, build_models(args))

    node = resolve_node(args.node)
    shard = None
    if args.shard:
        i, n = args.shard.split("/")
        shard = (int(i), int(n))
    tasks = load_tasks(Path(args.tasks), shard)
    log(f"variant={args.variant} node={node} tasks={len(tasks)} workers={args.workers}")

    summary = args.out / "summary.jsonl"
    with summary.open("a", encoding="utf-8") as sink:
        if args.workers <= 1:
            results = (run_task(t, args, node) for t in tasks)
        else:
            pool = ThreadPoolExecutor(max_workers=args.workers)
            futures = [pool.submit(run_task, t, args, node) for t in tasks]
            results = (f.result() for f in as_completed(futures))
        for res in results:
            print(json.dumps(res, ensure_ascii=False), flush=True)
            sink.write(json.dumps(res, ensure_ascii=False) + "\n")
            sink.flush()

    done = sum(1 for p in args.out.glob("*.json") if p.name != "summary.jsonl")
    log(f"finished {done}/{len(tasks)}; grade the produced patches with the official harness")


if __name__ == "__main__":
    main()
