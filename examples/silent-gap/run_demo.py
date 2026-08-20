#!/usr/bin/env python3
"""Reproduce the 30-second FAIL without a real graph tool.

Expected: impact-audited exits 2 because fake_graph.py omits caller_c.py.
This script itself exits 0 when that expected FAIL is reproduced.
"""
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
AUDITOR = REPO / "impact_audited.py"
GRAPH = (
    f"{shlex.quote(sys.executable)} {shlex.quote(str(HERE / 'fake_graph.py'))} {{sym}}"
)


def main():
    proc = subprocess.run(
        [
            sys.executable,
            str(AUDITOR),
            "audited",
            "--path",
            str(HERE),
            "--graph",
            GRAPH,
        ],
        cwd=str(REPO),
    )
    if proc.returncode != 2:
        print(
            f"expected exit 2 (missing callers), got {proc.returncode}",
            file=sys.stderr,
        )
        return 1
    print("Demo PASS: expected FAIL reproduced (missing caller_c.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
