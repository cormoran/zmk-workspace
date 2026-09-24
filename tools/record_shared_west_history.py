#!/usr/bin/env python3
"""Append task history for shared West profiles and worktrees."""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKSPACES = ROOT / "ws"


def profile_path(value: str | Path) -> Path:
    candidate = Path(value)
    if len(candidate.parts) == 1:
        candidate = WORKSPACES / candidate
    candidate = candidate.resolve(strict=True)
    if (candidate.parent != WORKSPACES.resolve()
            or not (candidate / "workspace-config/profile.json").is_file()):
        raise ValueError(f"not a shared West profile under {WORKSPACES}: {candidate}")
    return candidate


def safe_branch(branch: str) -> Path:
    path = Path(branch)
    if (not branch or path.is_absolute()
            or any(part in (".", "..") for part in branch.split("/"))):
        raise ValueError(f"invalid branch: {branch}")
    result = subprocess.run(
        ["git", "check-ref-format", "--branch", branch], capture_output=True, text=True
    )
    if result.returncode:
        raise ValueError(f"invalid branch: {branch}")
    return path


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=path, text=True).strip()


def append(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    with path.open("ab") as output:
        fcntl.flock(output, fcntl.LOCK_EX)
        output.write(line)
        output.flush()
        fcntl.flock(output, fcntl.LOCK_UN)


def base_entry(kind: str, profile: Path, task: str) -> dict:
    if not task.strip():
        raise ValueError("--task must describe the task")
    return {
        "event": kind,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "task": task.strip(),
        "profile": profile.name,
    }


def record_profile(profile: str | Path, repo: str | Path, task: str) -> Path:
    profile = profile_path(profile)
    repo = Path(repo).resolve(strict=True)
    metadata = json.loads((profile / "workspace-config/profile.json").read_text(encoding="utf-8"))
    entry = base_entry("profile_created", profile, task)
    entry.update({
        "source_repo": str(repo),
        "source_commit": git(repo, "rev-parse", "HEAD"),
        "zephyr_sha": metadata["zephyr_sha"],
        "zmk_branch": metadata["zmk_branch"],
    })
    path = profile / "log.jsonl"
    append(path, entry)
    return path


def record_worktree(profile: str | Path, repo: str | Path, branch: str, task: str,
                    worktree: str | Path | None = None) -> Path:
    profile = profile_path(profile)
    repo = Path(repo).resolve(strict=True)
    branch_path = safe_branch(branch)
    target = (Path(worktree) if worktree else profile / f"wt-{repo.name}" / branch_path).resolve(strict=True)
    if not target.is_relative_to(profile):
        raise ValueError(f"worktree is outside profile: {target}")
    if git(target, "branch", "--show-current") != branch:
        raise ValueError(f"worktree is not on branch {branch}: {target}")
    common_target = (target / git(target, "rev-parse", "--git-common-dir")).resolve()
    common_repo = (repo / git(repo, "rev-parse", "--git-common-dir")).resolve()
    if common_target != common_repo:
        raise ValueError(f"worktree does not belong to {repo}: {target}")
    entry = base_entry("worktree_created", profile, task)
    entry.update({
        "source_repo": str(repo),
        "branch": branch,
        "worktree": str(target),
        "commit": git(target, "rev-parse", "HEAD"),
    })
    path = profile / repo.name / branch_path.parent / f"{branch_path.name}_log.jsonl"
    append(path, entry)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="event", required=True)
    for event in ("profile", "worktree"):
        command = sub.add_parser(event)
        command.add_argument("--profile", required=True)
        command.add_argument("--repo", required=True)
        command.add_argument("--task", required=True, help="short task or issue description")
        if event == "worktree":
            command.add_argument("--branch", required=True)
            command.add_argument("--worktree", help="override the standard wt-<repo>/<branch> location")
    args = parser.parse_args()
    try:
        if args.event == "profile":
            path = record_profile(args.profile, args.repo, args.task)
        else:
            path = record_worktree(args.profile, args.repo, args.branch, args.task, args.worktree)
    except (ValueError, FileNotFoundError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"error: {exc}\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
