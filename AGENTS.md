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

## ZMK project work

Before working on a ZMK project under this workspace, read
[`shared-west-profiles`](.agents/skills/shared-west-profiles/SKILL.md). Create
or use a worktree in a compatible shared West profile and follow that skill's
rules for dependency checks, worktree placement, updates, and builds.
