# Shared West profile experiment

Date: 2026-09-24. Pilot module: `zmk-behavior-runtime-sensor-rotate`.

## Goal and invariants

- One `.west` and one set of dependency checkouts per profile.
- Profile name uses the resolved Zephyr commit and the declared ZMK branch.
- A module keeps its standalone manifest; joining a profile checks all active
  dependency declarations before moving a worktree into it.
- `west update` is run from the profile, never as part of worktree creation.
- Existing standalone workspaces remain untouched during the pilot.

## Observations before implementation

- The 20 existing module workspaces form eight groups by resolved Zephyr and
  ZMK commits. The largest group has 12 modules.
- The largest group still contains five commits of
  `zmk-feature-custom-settings` and two of `zmk-west-commands`, despite
  identical Zephyr and ZMK commits. These projects declare floating `main`
  revisions, so a profile needs one explicit baseline and a compatibility
  check. Successful compilation remains necessary to prove compatibility.
- `west manifest --freeze` fails if inactive BabbleSim projects are not cloned;
  `west manifest --freeze --active-only` works.
- `west.manifest.Manifest.from_file()` could not resolve this repository's
  standalone manifest from an arbitrary source file because the self-import
  path was resolved relative to the repository root. A temporary metadata-only
  West topdir with symlinks to the module's `west/` and existing dependencies
  resolves it without `west init` or downloads.
- `/home/ubuntu/.west` already exists. `west init -l workspace-config` inside
  the new profile failed with "already initialized in /home/ubuntu". Creating
  the profile's `.west/config` directly and validating it with West avoids
  changing the unrelated parent workspace.

## Trial log

- [x] Resolved the pilot manifest in a temporary topdir with
  `west manifest --resolve --active-only`: 58 active projects, including ZMK
  branch `main+custom-studio-protocol` and Zephyr revision
  `v4.1.0+zmk-fixes`.
- [x] Created
  `zephyr-9df4b12b5af3_zmk-main+custom-studio-protocol` and updated its
  dependencies using the pilot's dependency tree as a West path cache. The
  first attempt stopped before downloads because of the ancestor `.west`;
  explicit local configuration succeeded without changing that ancestor.
- [x] `west topdir` inside the profile reports the profile directory.
- [x] `shared_west.py check` accepted the pilot module.
- [x] Created `shared-west-pilot` under
  `<profile>/zmk-behavior-runtime-sensor-rotate/`. `west topdir` from the
  worktree reports the profile directory.
- [x] From that worktree, `west zmk-build tests/zmk-config -m . -d ./build -q
  -P 4` built both `xiao_ble//zmk` targets successfully. Build output stayed
  inside the worktree.
- [x] `shared_west.py check` rejected `zmk-feature-fast-keymap`: it requires
  `main+custom-studio-protocol+fast-keymap`, while the profile uses
  `main+custom-studio-protocol`. It also reported an extra required project.
- [x] Pinned all 57 non-ZMK projects to their installed commits in the
  profile's `workspace-config/west.yml` and committed that local manifest.
- [x] `skill-creator`'s `quick_validate.py` accepted
  `skills/shared-west-profiles/SKILL.md`.
- [x] Linked the repository skill into `~/.codex/skills/` for local discovery.
- [x] Created an additional worktree from an existing branch and verified the
  same profile selection; removed that temporary test worktree and branch.

## What changed during the trial

The ZMK branch moved from `618f0832...` in the seed to `1fc72aaff...` while
the profile was initialized. This is expected when the profile uses a branch
name rather than a pinned ZMK commit. Zephyr remained at `9df4b12b...`.
`zmk-feature-custom-settings` and `zmk-west-commands` also advanced on their
declared `main` branches. The build passed with this combination.

The build command's existing auto-discovery also added this repository root as
a module because it has `zephyr/module.yml`. The two builds succeeded, but
future test commands should specify an explicit build directory per worktree
and review auto-discovered module paths when a build behaves unexpectedly.

## Current limits

- The script creates a profile from a module whose standalone dependencies
  are already installed. Worktree placement selects among existing profiles;
  it does not download a new profile automatically.
- Compatibility compares every *active* project's URL and declared revision.
  For floating branches such as `main`, equality of names does not mean a
  historically tested commit. All worktrees in a profile use its current
  checkout, so build tests are needed after a shared update.
- Existing standalone directories keep their own `.west`; the pilot created
  a new worktree because new worktrees do not inherit that untracked folder.
- The pilot did not delete any existing standalone dependency trees. Its new
  profile is about 4.6 GiB, so this experiment has not yet reclaimed disk
  space. Savings accrue when more worktrees use it and obsolete standalone
  dependency trees are removed after their owners migrate.
- Source repositories with different manifest layouts may require an explicit
  `--manifest` path. The pilot's manifest lives under `west/`.

## Luna agent forward test

Two independent Luna trials loaded `skills/shared-west-profiles/SKILL.md` and
used the tool rather than changing West settings by hand.

- Incompatible trial: `zmk-feature-fast-keymap` requested a new worktree in an
  existing profile. The agent ran `check` and `worktree`; both reported the
  ZMK revision mismatch (`main+custom-studio-protocol+fast-keymap` versus
  `main+custom-studio-protocol`) and the missing `zmk-workspace` project. It
  stopped. Git's worktree list, branch list, shared Zephyr/ZMK HEADs, and
  root status showed no new branch, worktree, or shared-dependency change.
- Compatible trial: the agent ran `check`, created
  `skill-forward-compatible` for `zmk-behavior-runtime-sensor-rotate`, checked
  `west topdir`, and built both `xiao_ble//zmk` targets with a local `build/`.
  It reported no unclear step. The extra trial worktree and branch were
  removed after inspection; `shared-west-pilot` remains as the pilot.

The first trial was explicitly limited to existing profiles. After observing
it, the skill now states the same boundary clearly: a dependency mismatch
must not trigger changes to an existing shared checkout; a new profile is a
separate provisioning task.
