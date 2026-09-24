# Developing ZMK itself with shared West dependencies

## Use case and current boundary

The intended loop is to edit ZMK, run ZMK's own tests and firmware builds,
then build a separate module against the same modified ZMK tree, including
uncommitted changes. This needs a dedicated development profile whose West
project path `zmk/` is the editable Git worktree. Module worktrees using that
profile remain under `wt-<repo>/<branch>/`.

`tools/shared_west.py` currently supports module profiles only. Its `init`
requires a module manifest with both ZMK and Zephyr, while ZMK's own manifest
is `zmk/app/west.yml`. Its `check` requires each dependency's HEAD to equal
`manifest-rev`, which would reject an edited ZMK branch. It has no command to
create or validate a ZMK development profile. **Do not treat the steps below
as an implemented helper interface.** Provisioning that profile safely is
follow-up tool work; do not relabel or modify a populated module profile as a
shortcut.

In particular, putting a ZMK worktree at `wt-zmk/<branch>` while leaving the
profile's `zmk/` checkout in place does not select the edited code. West,
ZMK's West commands, and module builds still resolve the profile's `zmk/`.
An explicit `west build -s <other-zmk>/app` may use that app's sources but does
not by itself establish that all ZMK modules, boards, and West commands came
from the same checkout; it is not the integration check described here.

## Development profile contract for the helper

- Create a separate profile per active ZMK development branch or experiment.
  Obtain the worktree from a source checkout at `projects/zmk` and place it at
  `ws/<dev-profile>/zmk`. Keep the profile's dependency manifest and `.west`
  local under `ws/`. Record the baseline ZMK URL, declared branch, base commit,
  Zephyr commit, and full active dependency requirements in profile metadata.
- Seed dependencies from a compatible manifest and install them in the new
  profile. Never change an existing shared profile's ZMK checkout or
  dependencies to make it a development profile. Separate profiles also keep
  concurrent ZMK branches from silently changing one another's builds.
- Check the full active manifest of every dependent module, including its
  imports, against the development profile. Allow ZMK's HEAD to move or its
  worktree to be dirty while checking the remaining dependencies at their
  recorded revisions. Also resolve ZMK's current `app/west.yml`; if its active
  dependency URL, revision, or path requirements change, provision a new
  compatible profile before claiming an integration build.
- Never run an unrestricted `west update` in a development profile: it can
  move or replace the ZMK worktree. A future update helper should select only
  non-ZMK projects from the profile topdir and recheck all affected worktrees.
  Do not run `west init` or `west update` from the ZMK or module worktrees.
- Use an explicit build directory for each ZMK test or firmware build and for
  each module worktree. Record the ZMK HEAD and whether its worktree was dirty
  with the build results; a dirty tree cannot be reproduced from the SHA
  alone. Keep temporary reports in `docs/local/`, not in Git.

## Workflow once that helper exists

1. Create the dedicated profile from a chosen baseline and ZMK branch; then
   verify `west topdir` from `ws/<dev-profile>/zmk` and that
   `west list zmk -f '{abspath}'` resolves to that same worktree.
2. Edit ZMK there. For a relevant ZMK test, run its existing `west test
   tests/<case>` or `app/run-test.sh`, setting `ZMK_BUILD_DIR` to an explicit
   directory in the ZMK worktree. ZMK's test runner uses `native_sim` and
   writes snapshots, logs, and executables under its build directory. Run a
   representative `west build -s ./app -d ./build/<target> -b <board> -- ...`
   when firmware compilation matters. Verify the expected artifact.
3. Place the dependent module's branch under `wt-<repo>/<branch>/` in the same
   development profile after the complete manifest check. Build it with a
   module-local `-d ./build`. Confirm `west topdir`,
   `west list zmk -f '{abspath}'`, and the configured ZMK source path all point
   to this profile's `zmk/`; a successful build alone does not prove which ZMK
   checkout it used.
4. If ZMK's manifest changes dependency requirements, or the module requests
   a different ZMK/Zephyr baseline, create a new profile. Retest the ZMK and
   module builds there. Keep the old profile for comparison until its work is
   finished.

This is a profile and helper design guide, not a claim that the current
`shared_west.py` supports the workflow. Until it does, report the missing
support instead of running the module helper against ZMK or altering an
existing shared profile by hand.
