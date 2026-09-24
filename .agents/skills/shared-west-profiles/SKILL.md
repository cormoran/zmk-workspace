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

## Choose the relevant guide

- For ordinary module branches, profile creation, compatibility checks,
  dependency changes, and integration-only modules, read
  [references/module-worktrees.md](references/module-worktrees.md).
- For changes to ZMK itself, ZMK's own tests, or building another module
  against modified ZMK, read
  [references/zmk-development.md](references/zmk-development.md). The current
  helper does not yet create ZMK development profiles; follow the guide's
  current-support boundary.
- When changing the profile workflow or diagnosing a failed setup, also read
  [the verified pilot and known limits](../../../docs/shared-west-experiment.md).
