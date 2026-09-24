# Working rules

- Make changes to this `zmk-workspace` repository in the current checkout.
  After verification succeeds, commit the changes promptly and push the
  current branch to `origin`.
- Use the Git name and email already configured for this repository. Do not
  change the Git identity for an AI agent. Add a trailer identifying the active
  model to every AI-authored commit. Replace `<active-model-name>` with the
  model currently in use:
  `Co-Authored-By: Codex <active-model-name> <codex@users.noreply.github.com>`.
- Store temporary investigation notes and build results, such as dated
  verification reports, in `docs/local/`. This directory is ignored by Git;
  do not commit its contents.

## zmk-workspace worktrees

When creating a Git worktree of this `zmk-workspace` repository, share the
main checkout's ignored `projects/` and `ws/` directories rather than creating
per-worktree copies. Codex runs
`.codex/hooks/link-shared-workspace-dirs.sh` on startup to create these
symlinks automatically. For a worktree created outside Codex, run that script
from the new worktree before doing ZMK work.

The setup is idempotent. It only creates a missing link and refuses to replace
an existing file, directory, or link to a different target. Do not remove or
reinitialize the shared directories from a worktree.

## ZMK project work

Before working on a ZMK project under this workspace, read
[`shared-west-profiles`](.agents/skills/shared-west-profiles/SKILL.md). Create
or use a worktree in a compatible shared West profile and follow that skill's
rules for dependency checks, worktree placement, updates, and builds.
