# Building a consumer with a different module dependency

## Pinned remote feature revision

For a committed feature revision available from the module's remote, keep
the consumer's declared manifest intact. Resolve its complete standalone
manifest (for DYA2, `config/west-standalone.yml`, which imports
`west-dependency.yml`). Check an existing profile against all active
requirements and installed HEADs; if none matches, use `shared_west.py init`
with that complete manifest and the consumer's initialized standalone
dependencies to create a baseline first. Fetch the module's remote branch in
`projects/<module>` and verify its exact commit. Then create a separate
profile whose West manifest pins that one project to
the commit. `tools/shared_west.py fork-pinned` does this, pins ZMK to the
baseline's installed commit, updates dependencies only in the new profile,
and validates the result:

```bash
python3 tools/shared_west.py fork-pinned <base-profile> <consumer> \
  <module-project> <full-commit-sha> --manifest config/west-standalone.yml \
  --task '<task>'
python3 tools/shared_west.py worktree <consumer> <new-branch> \
  --manifest config/west-standalone.yml --profile <new-profile> \
  --allow-pinned-overrides --task '<task>'
```

Run both from the workspace root in the Nix devShell. The worktree command
fetches the consumer's `origin/main` (or `cormoran/main`) before creating a
new branch. The override flag is valid only for this dedicated profile and
its named, pinned project. Ordinary `find` and `check` do not silently accept
the profile as compatible with the consumer's floating revision. Use
`check --allow-pinned-overrides` with the explicit profile when rechecking.

Before building, verify `west topdir`, `west list <module-project> -f
'{abspath} {revision}'`, the module checkout's HEAD and `manifest-rev`, and
the configured Zephyr module paths (for example `zephyr_modules.txt` in the
target's build directory). All must select the new profile's module exactly once.
Build in the consumer worktree's own directory and record the profile,
consumer and module HEADs and dirty states, target, and UF2 path under
`docs/local/`. Never alter the existing profile or use `ZMK_EXTRA_MODULES` to
replace a manifest project. A consumer that contains `zephyr/module.yml` may
need `west zmk-build -m .` to expose its board and shield; this adds the
consumer, not another copy of the pinned dependency.

## Editable local dependency

Use this guide when an edited module needs validation through a consumer's
firmware. For example, build `zmk-keyboard-dya2` with local changes to
`zmk-feature-custom-settings`, possibly alongside temporary keyboard changes.

## Choose the integration baseline

- Resolve the consumer's complete active manifest, including imports. The
  consumer's ZMK, Zephyr, and other dependencies define the integration
  baseline. Check the edited module's own complete test manifest separately;
  if the two baselines differ, use separate profiles for the module's standalone
  tests and the consumer integration build. Do not silently change either
  manifest to make `find` pass.
- Check the consumer's declared URL, revision, and path for the edited module.
  The profile must include that project at its West path. A build tests local
  edits only when West and Zephyr actually use that path. A worktree placed at
  `wt-<module>/<branch>` does not replace a project already installed at
  `<profile>/<module>`.
- Give an experiment that edits a dependency its own integration profile.
  Keep shared profiles immutable for other worktrees. The editable dependency
  is a Git worktree at the profile's declared project path, on a feature
  branch; other dependencies remain at the checked baseline. Put the consumer
  branch in `wt-<consumer>/<branch>` in that same profile. Use a short-lived
  consumer branch/worktree for temporary changes; do not edit its source
  checkout or another experiment's branch. Commit or discard those changes
  deliberately after validation.

## Check and build

Before each integration build, compare the consumer's complete active
requirements with the profile, allowing only the named editable dependency's
HEAD and working tree to differ from `manifest-rev`. Check all other project
HEADs and the ZMK path as usual. From the consumer worktree, verify `west
topdir` points to the integration profile and `west list
zmk-feature-custom-settings -f '{abspath}'` (or the relevant project name)
points to the edited module worktree. Verify the Zephyr module list or CMake
cache for each firmware target uses that same path and contains the module
only once. Do not rely on `-m`/`ZMK_EXTRA_MODULES` to override a module already
present in the West manifest; adding another copy may select the wrong source
or create a duplicate module.

Build the consumer's real hardware targets from its worktree, using its
`build.yaml` and a build directory local to that worktree. Use a pristine
configuration when switching module paths or dependency baselines. For Dya2,
select the relevant central and peripheral artifacts before testing the pair
on hardware. Record the consumer and edited module HEADs, dirty state or diff,
profile name, selected targets, and firmware artifact paths in `docs/local/`.
A successful build proves compilation of that exact combination; hardware
behavior still needs an explicit device test.

If the consumer changes an active manifest requirement, resolve it again and
provision another compatible profile. Never run unrestricted `west update` in
the integration profile: it may reset or move the editable dependency.
Update only the other required projects from the profile topdir, then recheck
all affected worktrees and rebuild.

## Current helper boundary

`tools/shared_west.py` creates ordinary module profiles and checks every
dependency HEAD against `manifest-rev`. It cannot create or validate a profile
whose dependency path is an editable worktree, and `worktree` places branches
under `wt-<repo>/`, not at the dependency's West path. Its successful `find` or
`check` result therefore does not establish this integration setup. Do not
move a module worktree into an existing shared profile, replace its dependency
checkout, or weaken the normal check to force a build. A dedicated integration
profile and an explicit check exception for its named editable dependency need
helper support before this workflow can be performed under shared profiles.
The `fork-pinned` workflow above is only for committed revisions, not local
edits. Until editable dependency support exists, report this boundary rather
than claim that a build from an ordinary shared profile tested local edits.
