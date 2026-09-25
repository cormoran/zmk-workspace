---
name: shared-west-profiles
description: Manage this workspace's shared West dependency profiles and compatible Git worktrees for ZMK modules or ZMK core development. Use for profile setup, compatibility checks, worktree placement, updates, and builds.
---

# Shared West profiles

Use `tools/shared_west.py` from the `zmk-workspace` root for the currently
supported module workflow. Source repositories live in `projects/<repo>`;
profiles and their worktrees live in `ws/<profile>`. The whole `ws/` tree is
local and ignored by Git. Never add profile manifests or build results to this
repository.

## Refresh the branch baseline before creating a worktree

For every new worktree branch, work from the source repository under
`projects/<repo>`. Run `git fetch origin` when that remote exists; otherwise,
run `git fetch cormoran`. Create the branch from the fetched `origin/main` or
`cormoran/main` respectively. Do not branch from local `main`, `HEAD`, another
remote, or an arbitrary commit. The shared-worktree helper performs this
fetch-and-baseline selection for its `worktree` command; omit `--start`.

## Record why each resource was created

- Give every `shared_west.py init` and `shared_west.py worktree` call a
  `--task 'short task or issue description'`. The helper records the task only
  after creation and compatibility checks succeed. Reuse the same description
  across repositories involved in one task, adding an issue URL or ID when
  available.
- Profile creation appends to `ws/<profile>/log.jsonl`. Worktree creation
  appends to `ws/<profile>/<repo>/<branch>_log.jsonl`; a branch containing `/`
  creates matching subdirectories. Entries include a UTC timestamp, the task,
  source repository, relevant commit, and resource path or baseline. These
  JSONL files are local under ignored `ws/` and are never committed.
- For a manually created profile or worktree supported by a guide, register
  it after validation with `python3 tools/record_shared_west_history.py
  profile --profile <profile> --repo projects/<repo> --task '<task>'` or
  `python3 tools/record_shared_west_history.py worktree --profile <profile>
  --repo projects/<repo> --branch <branch> --worktree <path> --task '<task>'`.
  The script validates the profile, branch, and Git worktree before appending.
  Do not register an attempted creation that failed.

## Rules for every profile

- A profile is a West topdir with its own `.west` and
  `workspace-config/west.yml`. The directory name is a hint, not proof of
  compatibility: check the complete active manifest and installed dependency
  revisions before placing or building a worktree.
- Keep a module's standalone manifest in its source repository. Resolve its
  complete test manifest, including imports; `west-dependency.yml` alone may
  omit ZMK or Zephyr requirements.
- Never change a populated shared profile's manifest or dependency HEADs to
  satisfy a different URL, revision, or path requirement. Provision a new
  compatible profile instead. Run dependency updates only from the profile,
  followed by compatibility checks and affected builds. Do not run `west init`
  or `west update` from a worktree.
- Use a separate build directory for each worktree. Before building, verify
  `west topdir` and the ZMK path selected by West. A floating revision such as
  `main` describes a branch policy; only a build tests the installed commit.
- For consumer firmware built with edits to a Zephyr module dependency, keep
  the Zephyr and ZMK baseline in a compatible shared profile. Put both the
  consumer and edited module worktrees under that profile and use
  `shared_west.py overlay-modules` to select the edited module for each build.
  The installed West project remains at its original path. Verify the generated
  Zephyr module list selects the worktree exactly once.

## Choose the relevant guide

- For ordinary module branches, profile creation, compatibility checks,
  dependency changes, and integration-only modules, read
  [references/module-worktrees.md](references/module-worktrees.md).
- For building consumer firmware with local changes to a Zephyr module
  dependency (and possibly temporary consumer changes), read
  [references/dependency-integration.md](references/dependency-integration.md).
- For building a consumer against a fixed commit from a dependency feature
  branch, read the pinned-revision section of that guide. This uses an
  isolated profile and an explicit compatibility-check exception; it does
  not place an editable dependency worktree at West's project path.
- For changes to ZMK itself, ZMK's own tests, or building another module
  against modified ZMK, read
  [references/zmk-development.md](references/zmk-development.md). The current
  helper does not yet create ZMK development profiles; follow the guide's
  current-support boundary.
- When changing the profile workflow or diagnosing a failed setup, also read
  [the verified pilot and known limits](../../../docs/shared-west-experiment.md).
