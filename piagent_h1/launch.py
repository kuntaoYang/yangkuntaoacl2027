"""Launch the exact same bundled Pi for H0 or H1; H1 adds an explicit extension.

H0 = stock Pi 1.4.0 bundle.  H1 = the same bundle plus the evidence-loop
extension (``-e extension.mjs``), which requires ``H1_ARTIFACT_DIR`` to point
outside the task workspace.  Only a Node >= 22 runtime is required.
"""

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Kept only as a convenience fallback for the original author's machine.
LEGACY_NODE = "/home/yangkuntao/ACL/Qwen3.5-9b-terminal2.1/2RSI/vendor/node-v22.20.0-linux-x64/bin/node"


def _node_major(path):
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30).stdout
        return int(out.strip().lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def resolve_node(explicit=None, minimum=22):
    rejected = []
    for cand in (explicit, os.environ.get("PI_NODE"), LEGACY_NODE, "node"):
        if not cand:
            continue
        path = cand if os.path.isabs(cand) else shutil.which(cand)
        if not path or not os.path.exists(path):
            continue
        major = _node_major(path)
        if major >= minimum:
            return path
        rejected.append(f"{path} (v{major})")
    detail = f"; found too old: {', '.join(rejected)}" if rejected else ""
    raise SystemExit(f"node >= {minimum} not found; pass --node or set PI_NODE{detail}")


def command(variant, args, node=None):
    if variant not in ("H0", "H1"):
        raise ValueError("variant must be H0 or H1")
    result = [
        node or resolve_node(),
        str(ROOT / "vendor/pi/cli.js"),
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
    ]
    if variant == "H1":
        result += ["-e", str(ROOT / "extension.mjs")]
    return result + args


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--variant", choices=["H0", "H1"], default="H1")
    p.add_argument("--node")
    p.add_argument("--print-command", action="store_true",
                   help="print the resolved command instead of running it")
    p.add_argument("pi_args", nargs=argparse.REMAINDER)
    opts = p.parse_args()
    args = opts.pi_args[1:] if opts.pi_args[:1] == ["--"] else opts.pi_args
    cmd = command(opts.variant, args, opts.node)

    if opts.variant == "H1" and not os.environ.get("H1_ARTIFACT_DIR"):
        os.environ["H1_ARTIFACT_DIR"] = str(ROOT / "artifacts" / time.strftime("%Y%m%d-%H%M%S"))
    if opts.variant == "H1":
        Path(os.environ["H1_ARTIFACT_DIR"]).mkdir(parents=True, exist_ok=True)
        print(f"[h1] artifacts -> {os.environ['H1_ARTIFACT_DIR']}", file=sys.stderr)

    if opts.print_command:
        print(" ".join(shlex.quote(c) for c in cmd))
        return 0
    return subprocess.call(cmd, env=os.environ)


if __name__ == "__main__":
    sys.exit(main())
