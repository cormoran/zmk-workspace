#!/usr/bin/env python3
"""Configure a repository to enforce the shared worktree branch baseline."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / ".githooks"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", help="Git repository to configure")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    git(repo, "rev-parse", "--git-dir")
    configured = subprocess.run(
        ("git", "config", "--local", "--get", "core.hooksPath"),
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if configured.returncode not in (0, 1):
        raise SystemExit(configured.stderr.strip())
    existing = configured.stdout.strip()
    if existing and Path(existing).resolve() != HOOKS:
        parser.error(f"{repo} already uses a different core.hooksPath: {existing}")
    git(repo, "config", "--local", "core.hooksPath", str(HOOKS))
    print(f"Installed shared worktree baseline hook for {repo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
