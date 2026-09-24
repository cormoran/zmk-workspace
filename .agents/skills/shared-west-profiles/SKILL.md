---
name: shared-west-profiles
description: Manage this ZMK workspace's shared West dependency profiles and place module Git worktrees under a compatible profile. Use for profile creation, compatibility checks, or worktree setup in this repository.
---

# Shared West profiles

Use `tools/shared_west.py` from the `zmk-workspace` repository root. Read
[`docs/shared-west-experiment.md`](../../../docs/shared-west-experiment.md) when
changing the profile workflow or diagnosing a failed setup; it records the
verified pilot and the known limits.

## Profile invariants

- A profile directory is the West topdir. Its `workspace-config/west.yml` is
  the only manifest that updates its dependencies. The name uses the Zephyr
  commit and ZMK branch, with a dependency suffix when the same pair needs a
  different dependency set. The directory name alone does not establish
  compatibility; check all active projects before placing a worktree.
- Resolve the complete test manifest, including its `west-test-dependency.yml`
  import, when checking a module. `west-dependency.yml` alone can omit ZMK and
  Zephyr revisions and must not be used to establish profile compatibility.
- Source Git checkouts live in `projects/<repo>`; shared profiles live in
  `ws/<profile>`. This repository tracks each profile's
  `workspace-config/west.yml` and `profile.json`. Its `.west`, dependencies,
  and `wt-<repo>` worktrees are ignored. Commit and push profile configuration
  changes in this repository after validation, following `AGENTS.md`.
- ZMK follows the named branch; other projects are pinned to commits after
  profile creation. Run updates from the profile, then recheck and build the
  worktrees using it. Do not run `west init` or `west update` inside a shared
  worktree.
- Each module keeps its committed standalone manifest. A worktree without a
  local `.west` uses the profile's `.west`; an existing standalone checkout
  with its own `.west` continues to use its own workspace.
- `/home/ubuntu/.west` may exist. Leave it alone: the profile's local
  `.west/config` takes precedence. `west init -l` can reject a nested profile
  in this situation, so the script writes and validates the small local
  configuration directly.

## Changing dependency requirements

A module's active manifest declarations define the profile requirements. A
change to a project's URL, revision, or path, including a ZMK or Zephyr
version change, must use a new profile. Never alter an existing profile's
`workspace-config/west.yml`, dependency HEADs, or run `west update` in a
shared worktree to force the new declaration.

1. In the existing shared worktree, change the complete module manifest and
   commit the change. It is still attached to the old dependency profile, so
   do not treat a build there as a test of the new dependency version.
2. Make a temporary detached seed checkout under `projects/` at that commit.
   Initialize its standalone dependencies using the module's manifest, so its
   `dependencies/` tree matches the proposed complete test manifest. This is
   provisioning work only; do not build the feature in the seed checkout.
3. Create a new profile from the seed, supplying the complete test manifest
   when it is not the tool's default:
   `python3 tools/shared_west.py init <seed-checkout> --manifest <complete-test-manifest>`.
   The tool generates a dependency suffix when the Zephyr and ZMK pair already
   has a profile with different requirements. Validate and commit the new
   root-tracked profile configuration, then push it as required by `AGENTS.md`.
4. Prefer a successor branch in the new profile, starting at the manifest
   change commit:
   `python3 tools/shared_west.py worktree <repo> <successor-branch> --start <commit> --profile <new-profile>`.
   Verify `west topdir` and build there with a worktree-local build directory.
   To retain the same branch name, first commit the changes and remove the old
   worktree, because `worktree` will not place a branch that Git already has
   checked out elsewhere. Remove the temporary seed checkout after the new
   profile is created.

## Workflow

1. To seed a profile, use a module checkout in `projects/<repo>` with its
   standalone dependencies already installed:
   `python3 tools/shared_west.py init <module-repo>`.
   This creates one dependency set and root-tracked profile configuration. It
   does not remove or change the source checkout.
   When the requested branch differs from the checkout, make a temporary
   detached worktree at that branch, link its `dependencies` to an existing
   standalone dependency tree with the same Zephyr revision, and pass its
   complete test manifest via `--manifest`. The tool re-resolves imports after
   updating ZMK and rejects a changed Zephyr revision. Remove the temporary
   seed worktree after profile creation.
2. Place a new or existing feature branch in a compatible profile with
   `python3 tools/shared_west.py worktree <module-repo> <feature> [--start REF]`.
   The script stages the checkout, resolves its manifest, checks every active
   dependency declaration, then moves it to `ws/<profile>/wt-<repo>/<feature>`.
   If several profiles satisfy the declarations, choose the intended baseline
   explicitly with `--profile <profile-name>`; the tool still checks its
   compatibility before moving the worktree.
   `--start` applies when creating a branch; an existing branch must be free
   in Git's worktree list.
   If no profile matches, report the differing project names and revisions.
   Leave the existing profile and its checkouts untouched: do not edit its
   manifest, change dependency HEADs, or run `west update` to force a match.
   Create a separate profile from a matching standalone checkout only when
   the task includes provisioning another profile. When the request is
   limited to existing profiles, stop without leaving a new branch or
   worktree.
3. Verify `west topdir` from the new worktree and run the module's relevant
   build with an explicit worktree-local `-d ./build`. The pilot passed both
   `xiao_ble//zmk` targets using
   `west zmk-build tests/zmk-config -m . -d ./build -q -P 4`.

For a module with no standalone West manifest or build target, an integration
worktree can be placed manually only after checking that the profile manifest
declares the same repository URL and branch, and its installed dependency HEAD
equals the requested source branch commit. Verify `west topdir` in that
worktree and build a dependent project that uses that exact installed commit.
Report this as an integration build, not a standalone module build.

Use `python3 tools/shared_west.py check <profile> <repo>` to inspect an
existing module. Floating revisions such as `main` express a shared branch
policy, not a tested SHA; builds establish compatibility after an update.
