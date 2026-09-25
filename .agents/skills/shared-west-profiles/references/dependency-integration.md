# Building a consumer with a different module dependency

Use one compatible consumer profile for both local edits and a committed
feature revision of a Zephyr module. Select the module worktree explicitly
for the build. The consumer's manifest and the profile's installed dependency
checkouts stay at their declared baseline.

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

## Fixed remote feature revision

Use the same profile and overlay commands above for a committed module
revision. Fetch the feature branch into `projects/<module>` and verify the full
commit SHA exists there before creating the module worktree:

```bash
git -C projects/<module> fetch origin <feature-branch>
git -C projects/<module> cat-file -t <full-commit-sha>
```

Use `cormoran` when `origin` is absent. `cat-file` must print `commit`.
Create the module worktree with `--overlay-for` as shown above; a new branch
starts from the freshly fetched `origin/main` (or `cormoran/main`). On that
new, clean branch, move HEAD to the requested feature commit and verify it:

```bash
git -C ws/<profile>/wt-<module>/<module-branch> reset --hard <full-commit-sha>
git -C ws/<profile>/wt-<module>/<module-branch> rev-parse HEAD
```

Only run `reset --hard` on the new, clean module worktree. An existing branch
already at the desired commit can be placed with the same `worktree` command
without resetting it. Run `overlay-modules` again immediately before each
build, inspect `zephyr_modules.txt`, and record the module HEAD with the build
result. The profile's `west list <module>` continues to name its installed
checkout; it does not indicate which module CMake compiled. If the feature
commit changes the module's own build dependencies, verify those requirements
separately and use a compatible profile for its standalone tests.
