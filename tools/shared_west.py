#!/usr/bin/env python3
"""Create shared West profiles and place module worktrees in compatible ones.

The module's own west manifest remains the source of its requirements.  A
profile has one West configuration and one checkout of each dependency.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "projects"
WORKSPACES = ROOT / "ws"


class ProfileError(Exception):
    pass


def repository_path(value: str) -> Path:
    candidate = Path(value)
    if len(candidate.parts) == 1 and (PROJECTS / candidate).is_dir():
        return PROJECTS / candidate
    return candidate.resolve()


def workspace_path(value: str) -> Path:
    candidate = Path(value)
    if len(candidate.parts) == 1 and (WORKSPACES / candidate).is_dir():
        return WORKSPACES / candidate
    return candidate.resolve()


def run(*args: str, cwd: Path, capture: bool = True) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=capture)
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise ProfileError(f"{' '.join(args)} failed: {detail}")
    return result.stdout.strip() if capture else ""


def git(path: Path, *args: str) -> str:
    return run("git", *args, cwd=path)


def manifest_file(repo: Path, supplied: str | None) -> str:
    if supplied:
        candidate = supplied
    elif (repo / ".west/config").exists():
        config = configparser.ConfigParser()
        config.read(repo / ".west/config")
        candidate = str(Path(config["manifest"]["path"]) / config["manifest"].get("file", "west.yml"))
    else:
        candidate = "west/west-test-standalone.yml"
    if Path(candidate).is_absolute() or ".." in Path(candidate).parts:
        raise ProfileError("manifest path must stay inside the repository")
    if not (repo / candidate).is_file():
        raise ProfileError(f"manifest not found: {repo / candidate}")
    return candidate


def resolved(repo: Path, manifest: str, dependencies: Path) -> dict:
    """Resolve a module manifest using existing dependencies, without west init."""
    manifest_path = Path(manifest)
    if len(manifest_path.parts) < 2:
        raise ProfileError("expected a manifest below west/ or config/")
    manifest_dir = manifest_path.parts[0]
    with tempfile.TemporaryDirectory(prefix="shared-west-") as tmp:
        top = Path(tmp)
        (top / ".west").mkdir()
        (top / manifest_dir).symlink_to(repo / manifest_dir, target_is_directory=True)
        (top / "dependencies").symlink_to(dependencies, target_is_directory=True)
        (top / ".west/config").write_text(
            "[manifest]\npath = " + manifest_dir + "\nfile = "
            + str(Path(*manifest_path.parts[1:])) + "\n",
            encoding="utf-8",
        )
        return yaml.safe_load(run("west", "manifest", "--resolve", "--active-only", cwd=top))["manifest"]


def projects(doc: dict) -> dict[str, dict]:
    return {p["name"]: p for p in doc["projects"]}


def requirements_for(doc: dict) -> dict[str, dict]:
    return {
        name: {"url": p["url"], "revision": p["revision"], "path": p["path"]}
        for name, p in projects(doc).items()
    }


def profile_manifest(doc: dict, zephyr_sha: str) -> dict:
    output = {"manifest": {"group-filter": doc.get("group-filter", []), "projects": [], "self": {"path": "workspace-config"}}}
    for project in doc["projects"]:
        item = dict(project)
        path = Path(item["path"])
        if path.parts[0] != "dependencies":
            raise ProfileError(f"unexpected dependency path: {path}")
        item["path"] = str(Path(*path.parts[1:]))
        if item["name"] == "zephyr":
            item["revision"] = zephyr_sha
        output["manifest"]["projects"].append(item)
    return output


def profile_name(zephyr_sha: str, zmk_branch: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._+-]+", "-", zmk_branch).strip(".-")
    if not slug:
        raise ProfileError("invalid ZMK branch name")
    if slug != zmk_branch:
        slug += "-" + hashlib.sha256(zmk_branch.encode()).hexdigest()[:8]
    return f"zephyr-{zephyr_sha[:12]}_zmk-{slug}"


def dependencies_at(repo: Path) -> Path:
    path = repo / "dependencies"
    if not path.is_dir():
        raise ProfileError(f"existing dependencies are required: {path}")
    return path


def profile_data(profile: Path) -> dict:
    path = profile / "workspace-config/profile.json"
    if not path.is_file():
        raise ProfileError(f"not a shared West profile: {profile}")
    return json.loads(path.read_text(encoding="utf-8"))


def create(args: argparse.Namespace) -> None:
    repo = repository_path(args.repo)
    manifest = manifest_file(repo, args.manifest)
    deps = dependencies_at(repo)
    doc = resolved(repo, manifest, deps)
    by_name = projects(doc)
    try:
        zmk_branch = by_name["zmk"]["revision"]
        zephyr_revision = by_name["zephyr"]["revision"]
    except KeyError as exc:
        raise ProfileError(f"missing required project: {exc}") from exc
    if re.fullmatch(r"[0-9a-f]{40}", zmk_branch):
        raise ProfileError("ZMK revision is a SHA, not a branch; choose a branch-based module manifest")
    zephyr = deps / Path(by_name["zephyr"]["path"]).relative_to("dependencies")
    zephyr_sha = git(zephyr, "rev-parse", "manifest-rev")
    if git(zephyr, "rev-parse", "HEAD") != zephyr_sha:
        raise ProfileError("source Zephyr HEAD differs from manifest-rev; update the source workspace first")
    name = profile_name(zephyr_sha, zmk_branch)
    requirements = requirements_for(doc)
    profile = WORKSPACES / name
    if profile.exists():
        existing = profile_data(profile)["requirements"]
        if all(existing.get(project) == requirement for project, requirement in requirements.items()):
            raise ProfileError(f"compatible profile already exists: {profile}")
        digest = hashlib.sha256(json.dumps(requirements, sort_keys=True).encode()).hexdigest()[:8]
        profile = WORKSPACES / f"{name}_deps-{digest}"
        if profile.exists():
            raise ProfileError(f"profile already exists: {profile}")

    # Keep the resolved dependency list stable. ZMK follows its named branch;
    # Zephyr stays at the commit used to name the profile.
    output = profile_manifest(doc, zephyr_sha)
    metadata = {
        "format": 1,
        "zephyr_sha": zephyr_sha,
        "zephyr_revision": zephyr_revision,
        "zmk_branch": zmk_branch,
        "requirements": requirements,
    }
    config = profile / "workspace-config"
    config.mkdir(parents=True)
    (config / "west.yml").write_text(yaml.safe_dump(output, sort_keys=False), encoding="utf-8")
    (config / "profile.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    # west init refuses a nested topdir if an unrelated ancestor has .west.
    # A local West workspace is defined by this small configuration file.
    (profile / ".west").mkdir()
    (profile / ".west/config").write_text(
        "[manifest]\npath = workspace-config\nfile = west.yml\n\n"
        "[zephyr]\nbase = zephyr\n",
        encoding="utf-8",
    )
    run("west", "manifest", "--validate", cwd=profile)
    if Path(run("west", "topdir", cwd=profile)) != profile:
        raise ProfileError("West did not select the new profile as its topdir")
    print(f"Created {profile}")
    run("west", "update", "--narrow", "--path-cache", str(deps), cwd=profile, capture=False)
    # Imported projects can change when ZMK or another floating project moves
    # from the seed checkout to the requested revision. Resolve again against
    # the profile's new checkouts and install the resulting manifest.
    for _ in range(3):
        current = resolved(repo, manifest, profile)
        current_requirements = requirements_for(current)
        if current_requirements["zephyr"]["revision"] != zephyr_revision:
            raise ProfileError(
                "Zephyr revision changed after updating imported projects; "
                "seed this profile from dependencies matching the target revision"
            )
        if current_requirements == requirements:
            break
        requirements = current_requirements
        output = profile_manifest(current, zephyr_sha)
        metadata["requirements"] = requirements
        (config / "west.yml").write_text(yaml.safe_dump(output, sort_keys=False), encoding="utf-8")
        (config / "profile.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        run("west", "manifest", "--validate", cwd=profile)
        run("west", "update", "--narrow", "--path-cache", str(deps), cwd=profile, capture=False)
    else:
        raise ProfileError("imported dependencies did not stabilize after three updates")
    # Keep only ZMK floating. Pin every other project to the commit that
    # was actually checked out, including projects declared as `main`.
    for item in output["manifest"]["projects"]:
        if item["name"] != "zmk":
            item["revision"] = git(profile / item["path"], "rev-parse", "manifest-rev")
    (config / "west.yml").write_text(yaml.safe_dump(output, sort_keys=False), encoding="utf-8")
    run("west", "manifest", "--validate", cwd=profile)
    check(profile, repo, manifest)
    print("Dependencies updated and non-ZMK revisions pinned")


def check(profile: Path, repo: Path, manifest: str) -> None:
    data = profile_data(profile)
    doc = resolved(repo, manifest, profile)
    actual = projects(doc)
    expected = data["requirements"]
    differences = []
    for name, project in actual.items():
        previous = expected.get(name)
        if previous is None:
            differences.append(f"{name}: missing from profile")
        else:
            for field in ("url", "revision", "path"):
                if project[field] != previous[field]:
                    differences.append(
                        f"{name}: {field} requires {project[field]}, profile has {previous[field]}"
                    )
    if differences:
        raise ProfileError("dependency mismatch:\n  " + "\n  ".join(differences))
    zephyr = profile / "zephyr"
    if git(zephyr, "rev-parse", "HEAD") != data["zephyr_sha"]:
        raise ProfileError("profile Zephyr HEAD differs from its pinned SHA")
    for name in actual:
        project = profile / Path(actual[name]["path"]).relative_to("dependencies")
        if not (project / ".git").exists():
            raise ProfileError(f"dependency is not installed: {project}")
        head = git(project, "rev-parse", "HEAD")
        if head != git(project, "rev-parse", "manifest-rev"):
            raise ProfileError(f"dependency HEAD differs from manifest-rev: {name}")
        revision = actual[name]["revision"]
        if re.fullmatch(r"[0-9a-f]{40}", revision) and head != revision:
            raise ProfileError(f"pinned dependency commit differs from profile HEAD: {name}")


def verify(args: argparse.Namespace) -> None:
    profile = workspace_path(args.profile)
    repo = repository_path(args.repo)
    check(profile, repo, manifest_file(repo, args.manifest))
    print(f"Compatible: {repo} -> {profile}")


def matching_profiles(repo: Path, manifest: str, candidates: list[Path]) -> tuple[list[Path], list[str]]:
    matches = []
    failures = []
    for profile in candidates:
        if not (profile / "workspace-config/profile.json").is_file():
            continue
        try:
            check(profile, repo, manifest)
            matches.append(profile)
        except (ProfileError, subprocess.SubprocessError, ValueError) as exc:
            failures.append(f"{profile.name}: {exc}")
    return matches, failures


def find(args: argparse.Namespace) -> None:
    repo = repository_path(args.repo)
    manifest = manifest_file(repo, args.manifest)
    matches, failures = matching_profiles(
        repo, manifest, sorted(WORKSPACES.glob("zephyr-*_zmk-*"))
    )
    if not matches:
        detail = "\n".join(failures)
        raise ProfileError(f"no compatible profiles\n{detail}")
    for profile in matches:
        print(profile.name)


def add_worktree(args: argparse.Namespace) -> None:
    repo = repository_path(args.repo)
    branch = args.branch
    if not branch or Path(branch).is_absolute() or ".." in Path(branch).parts:
        raise ProfileError("branch must be a safe relative path")
    run("git", "check-ref-format", "--branch", branch, cwd=repo)
    manifest = manifest_file(repo, args.manifest)
    branch_exists = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo,
        check=False,
    ).returncode == 0
    if branch_exists and args.start:
        raise ProfileError("--start is only valid when creating a new branch")
    if branch_exists:
        worktrees = run("git", "worktree", "list", "--porcelain", cwd=repo)
        if f"branch refs/heads/{branch}" in worktrees.splitlines():
            raise ProfileError(f"branch is already checked out in another worktree: {branch}")
    start = branch if branch_exists else (args.start or "HEAD")
    WORKSPACES.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="shared-west-worktree-", dir=WORKSPACES) as staging:
        stage = Path(staging) / "checkout"
        run("git", "worktree", "add", "--detach", str(stage), start, cwd=repo, capture=False)
        try:
            if not (stage / manifest).is_file():
                raise ProfileError(f"manifest not found at start revision: {manifest}")
            candidates = (
                [workspace_path(args.profile)] if args.profile
                else sorted(WORKSPACES.glob("zephyr-*_zmk-*"))
            )
            matches, failures = matching_profiles(stage, manifest, candidates)
            if len(matches) != 1:
                detail = "\n".join(failures)
                raise ProfileError(f"expected one compatible profile, found {len(matches)}\n{detail}")
            profile = matches[0]
            target = profile / f"wt-{repo.name}" / branch
            if target.exists():
                raise ProfileError(f"worktree path already exists: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            run("git", "worktree", "move", str(stage), str(target), cwd=repo)
            try:
                if branch_exists:
                    run("git", "switch", branch, cwd=target)
                else:
                    run("git", "switch", "-c", branch, cwd=target)
            except ProfileError:
                print(f"Worktree is at {target}, detached; branch checkout failed", file=sys.stderr)
                raise
            print(f"Created {target}")
            print(f"West topdir: {run('west', 'topdir', cwd=target)}")
        finally:
            if stage.exists():
                run("git", "worktree", "remove", "--force", str(stage), cwd=repo)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create_parser = sub.add_parser("init", help="create a profile from an initialized module workspace")
    create_parser.add_argument("repo")
    create_parser.add_argument("--manifest")
    create_parser.set_defaults(action=create)
    check_parser = sub.add_parser("check", help="check a module against a profile")
    check_parser.add_argument("profile")
    check_parser.add_argument("repo")
    check_parser.add_argument("--manifest")
    check_parser.set_defaults(action=verify)
    find_parser = sub.add_parser("find", help="list profiles compatible with a module")
    find_parser.add_argument("repo")
    find_parser.add_argument("--manifest")
    find_parser.set_defaults(action=find)
    worktree_parser = sub.add_parser("worktree", help="create a branch worktree in its compatible profile")
    worktree_parser.add_argument("repo")
    worktree_parser.add_argument("branch")
    worktree_parser.add_argument("--start")
    worktree_parser.add_argument("--manifest")
    worktree_parser.add_argument("--profile", help="select a profile when several are compatible")
    worktree_parser.set_defaults(action=add_worktree)
    args = parser.parse_args()
    try:
        args.action(args)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
