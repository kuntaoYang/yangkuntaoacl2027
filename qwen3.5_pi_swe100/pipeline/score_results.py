#!/usr/bin/env python3
"""Score the generated patches with the official SWE-bench harness.

Reads *.json result files produced by runner.py, pulls the official per-instance
image through the docker proxy, runs the harness for a batch of instances, then
writes score/score_status back into the result files.

Resumable: instances already marked `evaluated` are skipped.
"""
import argparse
import concurrent.futures
import fcntl
import glob
import json
import os
import subprocess
import sys
import threading
import time

PIPE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(PIPE_DIR)
VENV_PY = os.path.join(ROOT, "eval-venv", "bin", "python")
DATASET = os.path.join(PIPE_DIR, "dataset_verified_full.json")
DEFAULT_INST_DIR = os.path.join(ROOT, "1RSI")
REPORT_DIR = os.path.join(ROOT, "eval_runs")
TMP_DIR = os.path.join(ROOT, "eval_tmp")
LOCK_DIR = os.path.join(TMP_DIR, "img_locks")
PROXY = "docker.1ms.run"
MIRRORS = ["docker.1ms.run"]
MODEL = "Qwen3.5-9B-piagent"
# Per-instance test timeout passed to the harness. Some suites (sympy) need
# more than the official 1800s default, so it is overridable from the CLI.
HARNESS_TIMEOUT = 1800


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# The agent shell injects a sandbox preload (LD_PRELOAD=sbox.so) whose shared
# memory dies with the shell session.  Long-lived children then dereference a
# stale policy object and die with SIGSEGV, so strip it for every subprocess.
SAFE_ENV = {k: v for k, v in os.environ.items()
            if k not in ("LD_PRELOAD", "SBOX_SHM_NAME", "TRAE_SANDBOX_SBOX_ID",
                         "TRAE_SANDBOX_TRACE_FILE")}


def sh(cmd, timeout=1800, check=False):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=SAFE_ENV)
    if check and p.returncode != 0:
        raise RuntimeError(f"{cmd[:2]} failed: {p.stderr.strip()[:300]}")
    return p


def image_key(instance_id: str) -> str:
    return f"swebench/sweb.eval.x86_64.{instance_id.replace('__', '_1776_', 1)}:latest"


def ensure_image(instance_id: str) -> None:
    key = image_key(instance_id)
    # Cross-process lock: the prefetcher and every scorer may want the same
    # image at the same time, and concurrent pulls of one tag corrupt it.
    os.makedirs(LOCK_DIR, exist_ok=True)
    with open(os.path.join(LOCK_DIR, instance_id.replace("/", "_") + ".lock"), "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        if sh(["docker", "image", "inspect", key]).returncode == 0:
            return
        last = None
        for attempt in range(1, 5):
            for mirror in MIRRORS:
                remote = f"{mirror}/{key}"
                log(f"pull {remote} (try {attempt})")
                try:
                    sh(["docker", "pull", remote], timeout=1200, check=True)
                    sh(["docker", "tag", remote, key], check=True)
                    return
                except Exception as exc:  # noqa: BLE001
                    last = exc
            time.sleep(15 * attempt)
        raise RuntimeError(f"cannot obtain {key}: {last}")


def drop_image(instance_id: str) -> None:
    key = image_key(instance_id)
    remote = f"{PROXY}/{key}"
    sh(["docker", "rmi", "-f", key])
    sh(["docker", "rmi", "-f", remote])


def load_results(inst_dir: str, shard: str = "", repos=None):
    out = []
    paths = sorted(glob.glob(os.path.join(inst_dir, "*.json")))
    if shard:
        i, n = (int(x) for x in shard.split("/"))
        paths = [p for k, p in enumerate(paths) if k % n == i]
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        if d.get("score_status") == "evaluated":
            continue
        # Repo filtering keeps one process on one repo, so the shared base
        # layers are downloaded once instead of once per parallel worker.
        if repos and d.get("instance_id", "").split("__")[0] not in repos:
            continue
        if not (d.get("patch") or "").strip():
            continue
        out.append((path, d))
    # Instances that already burned attempts (crashed harness) go to the back
    # of the queue so they never stall the whole shard.
    out.sort(key=lambda pd: int(pd[1].get("eval_attempts") or 0))
    return out


def run_batch(batch, workers: int, run_id: str) -> dict:
    def image_ready(pair):
        try:
            ensure_image(pair[1]["instance_id"])
            return True
        except Exception as exc:  # noqa: BLE001
            log(f"image unavailable for {pair[1]['instance_id']}: {exc}")
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        ready = list(ex.map(image_ready, batch))
    batch = [pair for pair, ok in zip(batch, ready) if ok]
    if not batch:
        return {}

    ids = [d["instance_id"] for _, d in batch]

    os.makedirs(TMP_DIR, exist_ok=True)
    pred_path = os.path.join(TMP_DIR, f"preds_{run_id}.jsonl")
    with open(pred_path, "w", encoding="utf-8") as f:
        for _, d in batch:
            f.write(json.dumps({
                "instance_id": d["instance_id"],
                "model_name_or_path": MODEL,
                "model_patch": d["patch"],
            }) + "\n")

    cmd = [VENV_PY, "-m", "swebench.harness.run_evaluation",
           "-d", DATASET, "-s", "test", "-i", *ids,
           "-p", pred_path, "-id", run_id, "-t", str(HARNESS_TIMEOUT),
           "--max_workers", str(workers), "--report_dir", REPORT_DIR]
    log(f"eval batch of {len(ids)} (run_id={run_id})")
    p = sh(cmd, timeout=7200)
    if p.returncode != 0:
        log(f"harness rc={p.returncode}: ids={ids} {p.stderr.strip()[-800:]}")
        with open(os.path.join(REPORT_DIR, f"stderr_{run_id}.log"), "w") as f:
            f.write(p.stderr)
        for iid in ids:
            ok = sh(["docker", "image", "inspect", image_key(iid)]).returncode == 0
            log(f"image present for {iid}: {ok}")

    report_path = os.path.join(REPORT_DIR, f"{MODEL}.{run_id}.json")
    if not os.path.exists(report_path):
        log(f"no report at {report_path}")
        return {}
    with open(report_path, encoding="utf-8") as f:
        rep = json.load(f)
    resolved = set(rep.get("resolved_ids") or [])
    errored = set(rep.get("error_ids") or [])
    # Anything not resolved and not errored counts as a failed attempt.
    return {d["instance_id"]: ("resolved" if d["instance_id"] in resolved
                              else "error" if d["instance_id"] in errored else "unresolved")
            for _, d in batch}


def save_result(path: str, d: dict) -> bool:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        log(f"cannot write {os.path.basename(path)}: {exc}")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def update_results(batch, outcomes: dict) -> None:
    for path, d in batch:
        outcome = outcomes.get(d["instance_id"])
        if outcome is None:
            # The harness crashed or produced no report: retry later, but do
            # not loop forever on an instance that can never be evaluated.
            attempts = int(d.get("eval_attempts") or 0) + 1
            d["eval_attempts"] = attempts
            if attempts >= 10:
                d["score"] = 0.0
                d["score_status"] = "evaluated"
                d["eval_outcome"] = "eval_failed"
                log(f"giving up on {d['instance_id']} after {attempts} attempts")
            save_result(path, d)
            continue
        d["score"] = 1.0 if outcome == "resolved" else 0.0
        d["score_status"] = "evaluated"
        d["eval_outcome"] = outcome
        save_result(path, d)


def mark_empty_patches(inst_dir: str) -> int:
    """A task that produced no patch can never resolve: score it 0 directly."""
    marked = 0
    for path in sorted(glob.glob(os.path.join(inst_dir, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        if d.get("score_status") == "evaluated":
            continue
        if (d.get("patch") or "").strip():
            continue
        d["score"] = 0.0
        d["score_status"] = "evaluated"
        d["eval_outcome"] = "empty_patch"
        if save_result(path, d):
            marked += 1
    if marked:
        log(f"marked {marked} empty-patch results as score 0")
    return marked


def main() -> None:
    global HARNESS_TIMEOUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst-dir", default=os.environ.get("SWE_INST_DIR", DEFAULT_INST_DIR))
    # Large batches with many concurrent docker builds segfault the harness,
    # so keep the batch small and the pytest worker count low.
    ap.add_argument("--batch-size", type=int, default=1)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--shard", default="", help="i/n: only score every n-th file starting at i")
    ap.add_argument("--repos", default="", help="comma separated repo prefixes this worker owns")
    ap.add_argument("--prefetch", type=int, default=10, help="pull images ahead of time")
    ap.add_argument("--limit", type=int, default=0, help="stop after N scored instances")
    ap.add_argument("--harness-timeout", type=int, default=1800,
                    help="per-instance test timeout for the harness")
    ap.add_argument("--keep-images", action="store_true")
    args = ap.parse_args()
    HARNESS_TIMEOUT = args.harness_timeout

    os.makedirs(REPORT_DIR, exist_ok=True)
    scored = 0
    fails = 0
    pulling = set()
    pull_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    def pull_one(iid: str) -> None:
        try:
            ensure_image(iid)
        except Exception as exc:  # noqa: BLE001
            log(f"prefetch failed for {iid}: {exc}")
        finally:
            pulling.discard(iid)

    def prefetch(pending) -> None:
        for _, d in pending[:args.prefetch]:
            iid = d["instance_id"]
            if iid in pulling:
                continue
            pulling.add(iid)
            pull_pool.submit(pull_one, iid)

    while True:
        mark_empty_patches(args.inst_dir)
        pending = load_results(args.inst_dir, args.shard,
                               [r for r in args.repos.split(",") if r])
        if not pending:
            log("nothing pending")
            break
        prefetch(pending)
        batch = pending[:args.batch_size]
        run_id = f"b{int(time.time())}"
        try:
            outcomes = run_batch(batch, args.workers, run_id)
        except Exception as exc:  # noqa: BLE001
            log(f"batch failed: {exc}")
            outcomes = {}
        update_results(batch, outcomes)
        ok = sum(1 for v in outcomes.values() if v == "resolved")
        log(f"batch done: {len(batch)} instance(s), resolved {ok}")
        if not args.keep_images:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                list(ex.map(lambda d: drop_image(d["instance_id"]), [d for _, d in batch]))
        scored += len(batch)
        if args.limit and scored >= args.limit:
            break
        time.sleep(2)


if __name__ == "__main__":
    main()
