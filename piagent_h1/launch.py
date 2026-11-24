"""Launch the exact same bundled Pi for H0 or H1; H1 adds an explicit extension."""
import argparse
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
DEFAULT_NODE = "/home/yangkuntao/ACL/Qwen3.5-9b-terminal2.1/2RSI/vendor/node-v22.20.0-linux-x64/bin/node"


def command(variant, args, node=None):
    if variant not in ("H0", "H1"):
        raise ValueError("variant must be H0 or H1")
    result = [node or os.environ.get("PI_NODE", DEFAULT_NODE), str(ROOT / "vendor/pi/cli.js"),
              "--no-extensions", "--no-skills", "--no-prompt-templates"]
    if variant == "H1":
        result += ["-e", str(ROOT / "extension.mjs")]
    return result + args


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--variant", choices=["H0", "H1"], default="H1")
    p.add_argument("--node")
    p.add_argument("pi_args", nargs=argparse.REMAINDER)
    opts = p.parse_args()
    args = opts.pi_args[1:] if opts.pi_args[:1] == ["--"] else opts.pi_args
    return subprocess.call(command(opts.variant, args, opts.node))


if __name__ == "__main__":
    sys.exit(main())
