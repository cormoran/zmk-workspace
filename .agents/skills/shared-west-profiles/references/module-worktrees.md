# Module worktrees in shared West profiles

The supported helper is `python3 tools/shared_west.py`, run from the
`zmk-workspace` root. It creates profiles from initialized standalone module
checkouts and places compatible Git worktrees under them.

## Create or select a profile

1. Keep the source checkout at `projects/<repo>`. To seed a new profile, first
   install its standalone `dependencies/` according to the module's complete
   test manifest. Then run `python3 tools/shared_west.py init <repo> --task
   '<task>'`; supply
   `--manifest <complete-test-manifest>` if the default
   `west/west-test-standalone.yml` is not the right file. The source checkout
   is left alone.
2. Use `python3 tools/shared_west.py find <repo>` to list compatible profiles,
   or `check <profile> <repo>` to inspect one. The helper compares every active
   project's URL, declared revision, and path, then checks installed HEADs.
3. Place a branch with `python3 tools/shared_west.py worktree <repo> <branch>
   --profile <profile> --task '<task>'`. The helper fetches `origin` (or
   `cormoran` when `origin` is absent), creates a new branch from that remote's
   `main`, stages the checkout, checks it against the selected profile, then
   moves it to `ws/<profile>/wt-<repo>/<branch>`. An existing branch must not
   already be checked out elsewhere. If several profiles match, select the
   intended baseline with `--profile`.
4. From the resulting worktree, confirm `west topdir` names the selected
   profile and `west list zmk -f '{abspath}'` names its `zmk/`. Build with a
   worktree-local directory, for example:

   ```bash
   west zmk-build tests/zmk-config -m . -d ./build -q -P 4
   ```

   Use the module's own build target when it differs. The pilot built both
   `xiao_ble//zmk` targets with this command.

If no profile matches, report the differing projects and revisions. Leave
existing profiles and checkouts untouched. Create another profile only when
the task includes provisioning one; a request limited to existing profiles
ends without a new branch or worktree.

## Changing dependency requirements

An active URL, revision, or path change, including a ZMK or Zephyr version
change, requires a new profile. The old worktree still uses its old profile
after editing the manifest, so a build there does not test the new dependency.

1. Commit the complete module manifest change in the existing worktree.
2. Make a temporary detached seed checkout under `projects/` at that commit
   and initialize its standalone dependencies from the complete test manifest.
   Use it only for provisioning, not feature builds.
3. Run `python3 tools/shared_west.py init <seed-checkout> --manifest
   <complete-test-manifest> --task '<task>'`. The tool gives a dependency suffix
   if the same Zephyr/ZMK pair needs a different dependency set. Validate the
   new profile.
4. After the manifest change reaches the selected remote's `main`, create a
   successor branch with `python3 tools/shared_west.py worktree <repo>
   <successor-branch> --profile <new-profile> --task '<task>'`. Check
   `west topdir` and build in that worktree. To retain the old branch name,
   first commit and remove its old worktree; a Git branch cannot be checked
   out in two worktrees. Remove the temporary seed checkout after provisioning.

When seeding from a branch different from the source checkout, use a temporary
detached worktree at that branch and a standalone dependency tree with the
same Zephyr revision. Pass the complete test manifest explicitly. The helper
re-resolves imports after updating ZMK and rejects a changed Zephyr revision.

## Other boundaries

Each profile's `workspace-config/west.yml` is the sole manifest for updating
its dependencies. In ordinary profiles ZMK follows the declared branch; other
projects are pinned to installed commits after profile creation. Existing
legacy pinned integration profiles also freeze ZMK; do not create another
profile for each Zephyr module feature commit. An existing standalone checkout
with its own `.west` keeps that workspace; a new worktree without `.west`
uses the profile's configuration. Leave any ancestor `/home/ubuntu/.west`
alone: the helper writes the profile's local `.west/config` directly because
`west init -l` may reject a nested profile.

For a module without a standalone West manifest or build target, manually
place an integration worktree only after verifying that the profile declares
the same repository URL and branch and that its installed dependency HEAD
equals the requested source branch commit. Verify `west topdir`, then build a
dependent project against that exact commit. Report an integration build,
not a standalone module build. Register the manually placed worktree with
`tools/record_shared_west_history.py worktree` as described in the main skill.
