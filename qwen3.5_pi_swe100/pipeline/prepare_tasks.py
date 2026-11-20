#!/usr/bin/env python3
"""Convert a SWE-bench dataset (jsonl or parquet) into runner.py's tasks.jsonl.

Usage:
    python prepare_tasks.py --input ../swebench_100/swebench_100.jsonl \
                            --output /data/qwen35_swebench/tasks.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys

FIELDS = [
    "instance_id",
    "repo",
    "base_commit",
    "problem_statement",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "version",
    "environment_setup_commit",
    "patch",
    "test_patch",
    "created_at",
]


def load_rows(path: str) -> list[dict]:
    if path.endswith(".parquet"):
        import pandas as pd

        return pd.read_parquet(path).to_dict(orient="records")
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--order", default="", help="optional file with instance_ids in the desired order")
    args = ap.parse_args()

    rows = load_rows(args.input)
    by_id = {r["instance_id"]: r for r in rows}
    if args.order and os.path.exists(args.order):
        ids = [x.strip() for x in open(args.order, encoding="utf-8") if x.strip()]
        missing = [i for i in ids if i not in by_id]
        if missing:
            sys.exit(f"missing instances: {missing[:5]}")
        rows = [by_id[i] for i in ids]

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for i, row in enumerate(rows, start=1):
            rec = {"index": f"{i:03d}"}
            for k in FIELDS:
                v = row.get(k, "")
                if k == "created_at":
                    v = str(v)
                rec[k] = v
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"wrote {len(rows)} tasks -> {args.output}")


if __name__ == "__main__":
    main()
