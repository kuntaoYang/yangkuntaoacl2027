#!/usr/bin/env python3
"""Run the Pi harness over SWE-bench Verified tasks inside an OpenPAI pod.

The pod gets the 500-task manifest and per-repo git mirrors from the
shared file system, checks out each task's base commit, runs `pi` in JSON
mode, then records the raw trajectory, token usage and the produced patch.
"""
import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

DATA_DIR = ""
REPOS_DIR = ""
OUT_DIR = ""
TRACE_DIR = ""
PATCH_DIR = ""
TARBALL_DIR = ""
WORK_ROOT = os.environ.get("SWE_WORK_DIR", "/tmp/qwen35_work")


def resolve_data_dir() -> str:
    candidates = []
    if os.environ.get("SWE_DATA_DIR"):
        candidates.append(os.environ["SWE_DATA_DIR"])
    candidates += [
        "/mnt/userdata/yangkuntao/qwen35_swebench",
        "/mnt/userdata/qwen35_swebench",
        "/data",
    ]
    for cand in candidates:
        if os.path.exists(os.path.join(cand, "tasks.jsonl")):
            return cand
    return candidates[0]

MODEL_NAME = "Qwen3.5-9B"
HARNESS = "piagent"
API_MODEL_ID = "Qwen/Qwen3.5-9B"
PROVIDER = "qwen"
BASE_URL = os.environ.get("SWE_API_BASE", "http://127.0.0.1:8000/v1")
API_KEY = os.environ.get("SWE_API_KEY", "local")

PI_MODELS = {
    "providers": {
        PROVIDER: {
            "name": "Qwen endpoint",
            "baseUrl": BASE_URL,
            "apiKey": API_KEY,
            "api": "openai-completions",
            "models": [
                {
                    "id": API_MODEL_ID,
                    "name": MODEL_NAME,
                    "reasoning": True,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 131072,
                    "maxTokens": 32768,
                    "samplingParams": {
                        "temperature": 1.0,
                        "top_p": 0.95,
                        "presence_penalty": 1.5,
                    },
                    # Qwen3.5's chat template only accepts system/user/assistant/tool.
                    "compat": {"supportsDeveloperRole": False},
                }
            ],
        }
    }
}

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

_lock_global = threading.Lock()
_pi_version = "unknown"


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def setup_pi_config() -> None:
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", "*"], check=False)
    cfg_dir = os.path.expanduser("~/.pi/agent")
    os.makedirs(cfg_dir, exist_ok=True)
    with open(os.path.join(cfg_dir, "models.json"), "w", encoding="utf-8") as f:
        json.dump(PI_MODELS, f)
    # Keep startup quiet and non-interactive.
    with open(os.path.join(cfg_dir, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"quietStartup": True, "defaultTools": ["read", "bash", "edit", "write"]}, f)


def mirror_repo(repo: str) -> str:
    name = repo.replace("/", "__") + ".git"
    dest = os.path.join(REPOS_DIR, name)
    if os.path.isdir(dest) and os.path.exists(os.path.join(dest, "HEAD")):
        return dest
    os.makedirs(REPOS_DIR, exist_ok=True)
    lock_path = dest + ".lock"
    with open(lock_path, "w") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        if os.path.isdir(dest) and os.path.exists(os.path.join(dest, "HEAD")):
            return dest
        tmp = dest + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        log(f"mirroring {repo}")
        subprocess.run(
            ["git", "clone", "--mirror", "--quiet", f"https://github.com/{repo}.git", tmp],
            check=True, timeout=3600,
        )
        os.replace(tmp, dest)
    return dest


def clone_worktree(mirror: str, base_commit: str, workdir: str) -> None:
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(os.path.dirname(workdir), exist_ok=True)
    subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", mirror, workdir],
                   check=True, timeout=600)
    subprocess.run(["git", "-C", workdir, "checkout", "--quiet", "--force", base_commit],
                   check=True, timeout=600)


def prepare_workdir(task: dict, workdir: str) -> str:
    """Materialize the task's source tree and return the baseline commit SHA."""
    idx = task["index"]
    tarball = os.path.join(TARBALL_DIR, f"{idx}.tar.gz")
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)
    if os.path.exists(tarball):
        subprocess.run(["tar", "-xzf", tarball, "-C", workdir, "--strip-components=1"],
                       check=True, timeout=1800)
        subprocess.run(["git", "init", "--quiet", "."], cwd=workdir, check=True, timeout=300)
        subprocess.run(["git", "-C", workdir, "add", "-A"], check=True, timeout=900)
        env = {**os.environ, "GIT_AUTHOR_NAME": "bench", "GIT_AUTHOR_EMAIL": "bench@local",
               "GIT_COMMITTER_NAME": "bench", "GIT_COMMITTER_EMAIL": "bench@local"}
        subprocess.run(["git", "-C", workdir, "commit", "--quiet", "--no-verify", "--allow-empty",
                        "-m", "baseline"], check=True, timeout=900, env=env)
        sha = subprocess.run(["git", "-C", workdir, "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
        return sha
    mirror = mirror_repo(task["repo"])
    clone_worktree(mirror, task["base_commit"], workdir)
    return task["base_commit"]


def extract_usage(trace_lines) -> dict:
    total = {"input_tokens_including_cache": 0, "cached_input_tokens": 0,
             "output_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0, "requests": 0}
    for line in trace_lines:
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


def run_pi(workdir: str, prompt: str, trace_path: str, err_path: str, timeout: int) -> tuple:
    cmd = [
        "pi", "--mode", "json",
        "--provider", PROVIDER, "--model", API_MODEL_ID,
        "--thinking", "high",
        "--no-session", "--offline", "-na", "-nc",
        prompt,
    ]
    with open(trace_path, "w", encoding="utf-8") as out, open(err_path, "w", encoding="utf-8") as err:
        try:
            proc = subprocess.run(cmd, cwd=workdir, stdout=out, stderr=err,
                                  timeout=timeout, text=True)
            return proc.returncode, "finished"
        except subprocess.TimeoutExpired:
            return None, "timeout"


def make_patch(workdir: str, baseline_commit: str) -> str:
    subprocess.run(["git", "-C", workdir, "add", "-A"], check=False, timeout=120)
    diff = subprocess.run(
        ["git", "-C", workdir, "diff", "--cached", "--binary", "--no-color", baseline_commit],
        capture_output=True, text=True, timeout=300,
    ).stdout
    return diff


def process_task(task: dict, args) -> dict:
    idx = task["index"]
    iid = task["instance_id"]
    result_path = os.path.join(OUT_DIR, f"{MODEL_NAME}，{HARNESS}，{idx}.json")
    if os.path.exists(result_path) and not args.force:
        return {"index": idx, "status": "skipped"}

    started = time.time()
    workdir = os.path.join(WORK_ROOT, idx)
    trace_path = os.path.join(TRACE_DIR, f"{idx}.jsonl")
    err_path = os.path.join(TRACE_DIR, f"{idx}.stderr.log")
    patch_path = os.path.join(PATCH_DIR, f"{idx}.diff")

    status = "error"
    error = ""
    patch = ""
    usage = {"input_tokens_including_cache": 0, "cached_input_tokens": 0,
             "output_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0, "requests": 0}
    rc = None
    trace_content = ""
    try:
        baseline = prepare_workdir(task, workdir)
        prompt = PROMPT_TEMPLATE.format(repo=task["repo"], problem=task["problem_statement"])
        rc, status = run_pi(workdir, prompt, trace_path, err_path, args.timeout)
        patch = make_patch(workdir, baseline)
        with open(patch_path, "w", encoding="utf-8") as f:
            f.write(patch)
        if os.path.exists(trace_path):
            # pi occasionally writes raw bytes that are not valid UTF-8; the
            # whole task must not crash just because the trace cannot be
            # decoded, so replace bad bytes instead of raising.
            with open(trace_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            usage = extract_usage(lines)
            trace_content = "".join(lines)
    except Exception as exc:  # noqa: BLE001
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
        log(f"[{idx}] {iid} failed: {error}\n{traceback.format_exc()}")

    result = {
        "model": MODEL_NAME,
        "harness": HARNESS,
        "task_id": idx,
        "instance_id": iid,
        "repo": task["repo"],
        "base_commit": task["base_commit"],
        "status": status,
        "score": None,
        "score_status": "pending_eval",
        "token_usage": usage,
        "patch": patch,
        "raw_trajectory": {f"{iid}.jsonl": {"content": trace_content}} if trace_content else {},
        "meta": {
            "api_model": API_MODEL_ID,
            "thinking": "high",
            "exit_code": rc,
            "duration_sec": round(time.time() - started, 1),
            "error": error,
            "pi_version": _pi_version,
        },
    }
    tmp_path = result_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    os.replace(tmp_path, result_path)
    shutil.rmtree(workdir, ignore_errors=True)
    log(f"[{idx}] {iid} {status} tokens={usage['total_tokens']} "
        f"patch_bytes={len(patch)} {result['meta']['duration_sec']}s")
    return {"index": idx, "status": status, "tokens": usage["total_tokens"]}


def load_tasks(args) -> list:
    tasks = []
    with open(os.path.join(DATA_DIR, "tasks.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                tasks.append(json.loads(line))
    if args.instances:
        wanted = set()
        with open(args.instances, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    wanted.add(line.strip())
        tasks = [t for t in tasks if t["instance_id"] in wanted]
    if args.shard:
        i, n = args.shard
        tasks = [t for k, t in enumerate(tasks) if k % n == i]
    return tasks


def main() -> None:
    global _pi_version, DATA_DIR, REPOS_DIR, OUT_DIR, TRACE_DIR, PATCH_DIR, TARBALL_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=int(os.environ.get("SWE_WORKERS", "24")))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("SWE_TASK_TIMEOUT", "2400")))
    parser.add_argument("--shard", type=lambda s: tuple(int(x) for x in s.split("/")), default=None)
    parser.add_argument("--instances", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    DATA_DIR = resolve_data_dir()
    REPOS_DIR = os.path.join(DATA_DIR, "repos")
    OUT_DIR = os.path.join(DATA_DIR, "outputs", "instances")
    TRACE_DIR = os.path.join(DATA_DIR, "outputs", "traces")
    PATCH_DIR = os.path.join(DATA_DIR, "outputs", "patches")
    TARBALL_DIR = os.path.join(DATA_DIR, "tarballs")
    log(f"data dir: {DATA_DIR}")

    for d in (OUT_DIR, TRACE_DIR, PATCH_DIR, WORK_ROOT):
        os.makedirs(d, exist_ok=True)
    setup_pi_config()
    try:
        _pi_version = subprocess.run(["pi", "--version"], capture_output=True, text=True,
                                     timeout=60).stdout.strip()
    except Exception:
        _pi_version = "unknown"
    log(f"pi version: {_pi_version}")

    tasks = load_tasks(args)
    log(f"tasks selected: {len(tasks)} workers={args.workers} timeout={args.timeout}")

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_task, t, args): t for t in tasks}
        for fut in as_completed(futures):
            done += 1
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                log(f"worker crash: {exc}")
            if done % 10 == 0:
                log(f"progress {done}/{len(tasks)}")
    log(f"ALL DONE {done}/{len(tasks)}")


if __name__ == "__main__":
    main()
