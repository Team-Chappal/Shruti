#!/usr/bin/env python
"""Refuse to start a rebuild on a dirty git tree.

Usage: tools/rebuild/dirty-check.sh
Exit codes:
  0  tree is clean (or only untracked files)
  1  tree has tracked modifications -> rebuild blocked
"""
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, check=False,
    )
    lines = [
        line for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("??")
    ]
    if lines:
        print("Rebuild blocked: tracked files are modified.", file=sys.stderr)
        for line in lines:
            print(f"  {line}", file=sys.stderr)
        print(
            "\nCommit or stash your changes before rebuilding.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
