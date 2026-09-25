#!/usr/bin/env python3
"""Create shared West profiles and place module worktrees in compatible ones.

The module's own west manifest remains the source of its requirements.  A
profile has one West configuration and one checkout of each dependency.
"""

from __future__ import annotations

import argparse
import configparser
import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from record_shared_west_history import record_profile, record_worktree


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


def branch_remote(repo: Path) -> str:
    remotes = set(git(repo, "remote").splitlines())
    for remote in ("origin", "cormoran"):
        if remote in remotes:
            return remote
    raise ProfileError("new worktree branches require an origin or cormoran remote")


def refreshed_main(repo: Path) -> str:
    remote = branch_remote(repo)
    run("git", "fetch", remote, cwd=repo, capture=False)
    baseline = f"{remote}/main"
    try:
        git(repo, "rev-parse", "--verify", f"refs/remotes/{baseline}")
    except ProfileError as exc:
        raise ProfileError(f"fetched remote does not provide {baseline}") from exc
    return baseline


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
    try:
        history = record_profile(profile, repo, args.task)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise ProfileError(f"profile created, but history registration failed: {exc}") from exc
    print("Dependencies updated and non-ZMK revisions pinned")
    print(f"Task history: {history}")


def fork_pinned(args: argparse.Namespace) -> None:
    """Make an isolated, commit-pinned consumer profile from a checked baseline."""
    base = workspace_path(args.base_profile)
    repo = repository_path(args.repo)
    manifest = manifest_file(repo, args.manifest)
    check(base, repo, manifest)
    baseline = profile_data(base)
    if args.project not in baseline["requirements"]:
        raise ProfileError(f"project is not in the baseline: {args.project}")
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        raise ProfileError("revision must be a full 40-character commit SHA")
    source = PROJECTS / args.project
    if not source.is_dir() or git(source, "cat-file", "-t", args.revision) != "commit":
        raise ProfileError(f"commit is not available in {source}: {args.revision}")
    original = baseline["requirements"][args.project]["revision"]
    if original == args.revision:
        raise ProfileError("the baseline already requires this revision")
    suffix = hashlib.sha256(f"{args.project}:{args.revision}".encode()).hexdigest()[:8]
    profile = WORKSPACES / f"{base.name}_pin-{suffix}"
    if profile.exists():
        raise ProfileError(f"profile already exists: {profile}")
    document = yaml.safe_load((base / "workspace-config/west.yml").read_text(encoding="utf-8"))
    entries = [p for p in document["manifest"]["projects"] if p["name"] == args.project]
    if len(entries) != 1:
        raise ProfileError(f"expected one manifest entry for {args.project}")
    entries[0]["revision"] = args.revision
    # Freeze the ZMK checkout too: this integration profile represents one
    # exact dependency set, even when the source profile follows a branch.
    zmk = next(p for p in document["manifest"]["projects"] if p["name"] == "zmk")
    if not re.fullmatch(r"[0-9a-f]{40}", zmk["revision"]):
        zmk["revision"] = git(base / zmk["path"], "rev-parse", "HEAD")
    metadata = copy.deepcopy(baseline)
    metadata["requirements"][args.project]["revision"] = args.revision
    metadata["pinned_overrides"] = {args.project: original}
    metadata["source_profile"] = base.name
    config = profile / "workspace-config"
    config.mkdir(parents=True)
    (config / "west.yml").write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    (config / "profile.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (profile / ".west").mkdir()
    (profile / ".west/config").write_text(
        "[manifest]\npath = workspace-config\nfile = west.yml\n\n[zephyr]\nbase = zephyr\n",
        encoding="utf-8",
    )
    run("west", "manifest", "--validate", cwd=profile)
    if Path(run("west", "topdir", cwd=profile)) != profile:
        raise ProfileError("West did not select the new profile as its topdir")
    run("west", "update", "--narrow", "--path-cache", str(base), cwd=profile, capture=False)
    check(profile, repo, manifest, allow_pinned_overrides=True)
    try:
        history = record_profile(profile, repo, args.task)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise ProfileError(f"profile created, but history registration failed: {exc}") from exc
    print(f"Created {profile}")
    print(f"Pinned {args.project} at {args.revision}")
    print(f"Task history: {history}")


def check(profile: Path, repo: Path, manifest: str, *, allow_pinned_overrides: bool = False) -> None:
    data = profile_data(profile)
    doc = resolved(repo, manifest, profile)
    actual = projects(doc)
    expected = data["requirements"]
    overrides = data.get("pinned_overrides", {}) if allow_pinned_overrides else {}
    differences = []
    if overrides:
        profile_manifest_doc = yaml.safe_load(
            (profile / "workspace-config/west.yml").read_text(encoding="utf-8")
        )
        pinned_entries = projects(profile_manifest_doc["manifest"])
        for name in overrides:
            if pinned_entries.get(name, {}).get("revision") != expected[name]["revision"]:
                differences.append(f"{name}: profile manifest does not pin the recorded revision")
    for name, project in actual.items():
        previous = expected.get(name)
        if previous is None:
            differences.append(f"{name}: missing from profile")
        else:
            for field in ("url", "revision", "path"):
                if project[field] != previous[field] and not (
                    field == "revision"
                    and name in overrides
                    and project[field] == overrides[name]
                    and re.fullmatch(r"[0-9a-f]{40}", previous[field])
                ):
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
    check(profile, repo, manifest_file(repo, args.manifest), allow_pinned_overrides=args.allow_pinned_overrides)
    print(f"Compatible: {repo} -> {profile}")


def matching_profiles(repo: Path, manifest: str, candidates: list[Path], *, allow_pinned_overrides: bool = False) -> tuple[list[Path], list[str]]:
    matches = []
    failures = []
    for profile in candidates:
        if not (profile / "workspace-config/profile.json").is_file():
            continue
        try:
            check(profile, repo, manifest, allow_pinned_overrides=allow_pinned_overrides)
            matches.append(profile)
        except (ProfileError, subprocess.SubprocessError, ValueError) as exc:
            failures.append(f"{profile.name}: {exc}")
    return matches, failures


def check_overlay(profile: Path, consumer: Path, manifest: str, module: Path) -> str:
    """Validate an editable module against the consumer's unchanged baseline."""
    check(profile, consumer, manifest)
    name = module.name
    requirement = profile_data(profile)["requirements"].get(name)
    if requirement is None:
        raise ProfileError(f"module is not a consumer dependency: {name}")
    installed = profile / Path(requirement["path"]).relative_to("dependencies")
    if installed.resolve() != Path(run("west", "list", name, "-f", "{abspath}", cwd=profile)):
        raise ProfileError(f"West selects a different project path for {name}")
    remote = branch_remote(module)
    source_url = git(module, "remote", "get-url", remote).removesuffix(".git")
    if source_url != requirement["url"].removesuffix(".git"):
        raise ProfileError(f"module remote differs from consumer manifest: {name}")
    return name


def overlay_modules(args: argparse.Namespace) -> None:
    profile = workspace_path(args.profile)
    consumer = repository_path(args.consumer)
    if Path(args.project).name != args.project or args.project in (".", ".."):
        raise ProfileError("project must be a source repository name")
    if Path(args.branch).is_absolute() or ".." in Path(args.branch).parts:
        raise ProfileError("branch must be a safe relative path")
    run("git", "check-ref-format", "--branch", args.branch, cwd=PROJECTS / args.project)
    module = (profile / f"wt-{args.project}" / args.branch).resolve()
    if not module.is_dir():
        raise ProfileError(f"module worktree not found: {module}")
    name = check_overlay(profile, consumer, manifest_file(consumer, args.consumer_manifest),
                         PROJECTS / args.project)
    if module != (profile / f"wt-{name}" / args.branch).resolve():
        raise ProfileError("module must be a branch worktree in the selected profile")
    if git(module, "branch", "--show-current") != args.branch:
        raise ProfileError(f"module worktree is not on branch {args.branch}")
    if (module / git(module, "rev-parse", "--git-common-dir")).resolve() != \
            (PROJECTS / name / git(PROJECTS / name, "rev-parse", "--git-common-dir")).resolve():
        raise ProfileError("module worktree belongs to a different repository")
    doc = yaml.safe_load(run("west", "manifest", "--resolve", "--active-only", cwd=profile))["manifest"]
    paths = []
    replaced = 0
    for project in doc["projects"]:
        path = profile / project.get("path", project["name"])
        if project["name"] == name:
            path = module
            replaced += 1
        if (path / "zephyr/module.yml").is_file() or (path / "zephyr/CMakeLists.txt").is_file():
            paths.append(str(path))
    if replaced != 1 or not ((module / "zephyr/module.yml").is_file() or
                             (module / "zephyr/CMakeLists.txt").is_file()):
        raise ProfileError(f"expected one Zephyr module project for {name}")
    print("-DZEPHYR_MODULES=" + ";".join(paths))


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
    overlay_consumer = repository_path(args.overlay_for) if args.overlay_for else None
    if overlay_consumer and not args.profile:
        raise ProfileError("--overlay-for requires an explicit --profile")
    if overlay_consumer and args.allow_pinned_overrides:
        raise ProfileError("--overlay-for cannot use pinned overrides")
    if args.allow_pinned_overrides and not args.profile:
        raise ProfileError("--allow-pinned-overrides requires an explicit --profile")
    branch = args.branch
    if not branch or Path(branch).is_absolute() or ".." in Path(branch).parts:
        raise ProfileError("branch must be a safe relative path")
    run("git", "check-ref-format", "--branch", branch, cwd=repo)
    manifest = manifest_file(overlay_consumer or repo,
                             args.consumer_manifest if overlay_consumer else args.manifest)
    branch_exists = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=repo,
        check=False,
    ).returncode == 0
    if branch_exists:
        worktrees = run("git", "worktree", "list", "--porcelain", cwd=repo)
        if f"branch refs/heads/{branch}" in worktrees.splitlines():
            raise ProfileError(f"branch is already checked out in another worktree: {branch}")
    start = branch if branch_exists else refreshed_main(repo)
    WORKSPACES.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="shared-west-worktree-", dir=WORKSPACES) as staging:
        stage = Path(staging) / "checkout"
        run("git", "worktree", "add", "--detach", str(stage), start, cwd=repo, capture=False)
        try:
            if not overlay_consumer and not (stage / manifest).is_file():
                raise ProfileError(f"manifest not found at start revision: {manifest}")
            candidates = (
                [workspace_path(args.profile)] if args.profile
                else sorted(WORKSPACES.glob("zephyr-*_zmk-*"))
            )
            if overlay_consumer:
                matches, failures = [], []
                for candidate in candidates:
                    try:
                        check_overlay(candidate, overlay_consumer, manifest, repo)
                        matches.append(candidate)
                    except ProfileError as exc:
                        failures.append(f"{candidate.name}: {exc}")
            else:
                matches, failures = matching_profiles(
                    stage, manifest, candidates, allow_pinned_overrides=args.allow_pinned_overrides
                )
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
            topdir = Path(run("west", "topdir", cwd=target))
            if topdir != profile:
                raise ProfileError(f"West selected the wrong topdir: {topdir}")
            try:
                history = record_worktree(profile, repo, branch, args.task, target)
            except (ValueError, OSError, subprocess.CalledProcessError) as exc:
                raise ProfileError(f"worktree created, but history registration failed: {exc}") from exc
            print(f"Created {target}")
            print(f"West topdir: {topdir}")
            print(f"Task history: {history}")
        finally:
            if stage.exists():
                run("git", "worktree", "remove", "--force", str(stage), cwd=repo)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create_parser = sub.add_parser("init", help="create a profile from an initialized module workspace")
    create_parser.add_argument("repo")
    create_parser.add_argument("--manifest")
    create_parser.add_argument("--task", required=True, help="short task or issue description for the profile log")
    create_parser.set_defaults(action=create)
    fork_parser = sub.add_parser("fork-pinned", help="create an isolated profile with one dependency pinned to a commit")
    fork_parser.add_argument("base_profile")
    fork_parser.add_argument("repo")
    fork_parser.add_argument("project")
    fork_parser.add_argument("revision")
    fork_parser.add_argument("--manifest")
    fork_parser.add_argument("--task", required=True)
    fork_parser.set_defaults(action=fork_pinned)
    check_parser = sub.add_parser("check", help="check a module against a profile")
    check_parser.add_argument("profile")
    check_parser.add_argument("repo")
    check_parser.add_argument("--manifest")
    check_parser.add_argument("--allow-pinned-overrides", action="store_true")
    check_parser.set_defaults(action=verify)
    find_parser = sub.add_parser("find", help="list profiles compatible with a module")
    find_parser.add_argument("repo")
    find_parser.add_argument("--manifest")
    find_parser.set_defaults(action=find)
    worktree_parser = sub.add_parser("worktree", help="create a branch worktree in its compatible profile")
    worktree_parser.add_argument("repo")
    worktree_parser.add_argument("branch")
    worktree_parser.add_argument("--manifest")
    worktree_parser.add_argument("--profile", help="select a profile when several are compatible")
    worktree_parser.add_argument("--allow-pinned-overrides", action="store_true")
    worktree_parser.add_argument("--overlay-for", help="consumer repository for an editable module worktree")
    worktree_parser.add_argument("--consumer-manifest", help="complete consumer manifest for --overlay-for")
    worktree_parser.add_argument("--task", required=True, help="short task or issue description for the worktree log")
    worktree_parser.set_defaults(action=add_worktree)
    overlay_parser = sub.add_parser("overlay-modules", help="print a ZEPHYR_MODULES CMake argument for an editable module")
    overlay_parser.add_argument("profile")
    overlay_parser.add_argument("consumer")
    overlay_parser.add_argument("project")
    overlay_parser.add_argument("branch")
    overlay_parser.add_argument("--consumer-manifest")
    overlay_parser.set_defaults(action=overlay_modules)
    args = parser.parse_args()
    try:
        args.action(args)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
