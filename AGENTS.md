# Working rules

- Make changes to this `zmk-workspace` repository in the current checkout.
  After verification succeeds, commit the changes promptly and push the
  current branch to `origin`.
- Before committing, set a repository-local Git identity for the active AI
  agent. Include the active model name in both fields, for example:
  `git config user.name "Codex (GPT-6)"` and
  `git config user.email "codex-gpt-6@agents.local"`. Do not use an
  automatically inferred system identity.
- Store temporary investigation notes and build results, such as dated
  verification reports, in `docs/local/`. This directory is ignored by Git;
  do not commit its contents.

## ZMK project work

Before working on a ZMK project under this workspace, read
[`shared-west-profiles`](.agents/skills/shared-west-profiles/SKILL.md). Create
or use a worktree in a compatible shared West profile and follow that skill's
rules for dependency checks, worktree placement, updates, and builds.
