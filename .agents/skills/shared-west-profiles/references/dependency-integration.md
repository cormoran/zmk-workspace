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

## Select one shared baseline

Resolve the consumer's complete active manifest, including imports. Its ZMK,
Zephyr, and other requirements define the firmware baseline. Select an
ordinary compatible profile with `find` or `check`. The edited module's own
standalone test manifest may need a different profile; it does not change the
consumer's firmware baseline. Keep both manifests intact.

For DYA2 and `zmk-feature-custom-settings`:

```bash
python3 tools/shared_west.py check <profile> zmk-keyboard-dya2 \
  --manifest config/west-standalone.yml
python3 tools/shared_west.py worktree zmk-keyboard-dya2 <consumer-branch> \
  --manifest config/west-standalone.yml --profile <profile> --task '<task>'
python3 tools/shared_west.py worktree zmk-feature-custom-settings <module-branch> \
  --overlay-for zmk-keyboard-dya2 \
  --consumer-manifest config/west-standalone.yml \
  --profile <profile> --task '<task>'
```

The second worktree command checks the consumer against the profile and the
module's remote against the consumer's project declaration. It fetches the
module's `origin/main` (or `cormoran/main`) before creating a new branch.
Both worktrees stay under `ws/<profile>/wt-<repo>/<branch>`. The profile's
installed module, Zephyr, and ZMK checkouts remain untouched. Use a separate
consumer branch for temporary config changes and commit or discard them after
validation.

## Build with the edited module

From the consumer worktree, generate the explicit Zephyr module list before
each build. The helper checks the consumer's complete manifest and all
installed dependency HEADs, then replaces only the named module path in the
list. The generated argument contains all other active Zephyr modules.

```bash
overlay="$(python3 /path/to/zmk-workspace/tools/shared_west.py overlay-modules \
  <profile> . zmk-feature-custom-settings <module-branch> \
  --consumer-manifest config/west-standalone.yml)"
west topdir
west list zmk -f '{abspath}'
west zmk-build -d ./build -q --pristine always \
  --extra-module-auto-discovery none -m . --cmake-args="$overlay"
```

Select the required targets with `zmk-build` options and DYA2's `build.yaml`.
The `-m .` entry supplies the consumer's boards and shields; it must not add
the edited dependency. Use a worktree-local build directory and a pristine
configuration after changing module paths. Do not use `ZMK_EXTRA_MODULES` to
add a second copy of the edited dependency.

For each target, inspect `build/<artifact>/zephyr_modules.txt`: the edited
module's worktree path must appear exactly once and the profile's installed
path for that module must be absent. Also check the firmware artifact exists.
Record the profile, consumer and edited module HEADs and dirty states, targets,
and artifact paths under `docs/local/`. Compilation does not test hardware
behavior; test the selected central and peripheral firmware on the pair when
device behavior matters.

If the consumer changes an active manifest requirement, select or create a
different compatible profile. Run dependency updates only from the profile
topdir, then recheck and rebuild affected worktrees. A module that is not a
Zephyr module, or whose repository URL differs from the consumer declaration,
cannot use this overlay workflow.
