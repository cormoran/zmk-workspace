# Local `main` worktree build report (2026-09-24)

This run used each repository's **local** `main` ref without fetching or
rebasing it. The source checkouts and their uncommitted changes were left
untouched. Each validation worktree is named `validation/main-build-20260924`;
the React project uses `projects/react-zmk-studio-worktrees/main-build-20260924`.

West modules were checked against their complete test manifests, placed under
a compatible profile, and built with `CMAKE_BUILD_PARALLEL_LEVEL=2 west
zmk-build tests/zmk-config -m . -d ./build -q -P 1`. DYA2 used `west
zmk-build . -m . -d ./build -q -P 1`. React used `npm run build` with existing
`node_modules`. Build artifacts and per-target `stdout_and_stderr.log` files
remain in each worktree's `build/` directory.

Summary: 19 passes (including one integration build), 2 build failures, and
4 cases blocked before worktree creation. Twenty-one validation worktrees were
created, and their HEADs all matched the local `main` refs.

| Project | Result | Targets | Profile / reason |
| --- | --- | ---: | --- |
| react-zmk-studio | PASS | npm build | Non-West worktree under `projects/` |
| zmk-behavior-runtime-sensor-rotate | PASS | 2/2 | `v0.3` custom profile |
| zmk-driver-animation | PASS | 1/1 | upstream `main` profile |
| zmk-driver-pmw3610-with-custom-studio-rpc | FAIL | 6/8 | shared custom profile; `temp_slot` API error |
| zmk-feature-codex | BLOCKED | — | Manifest pins ZMK SHA `fffa339c…`; profiles require a ZMK branch name |
| zmk-feature-custom-settings | PASS | 6/6 | shared custom profile |
| zmk-feature-custom-settings-behavior | PASS | 5/5 | shared custom profile |
| zmk-feature-default-layer | PASS | 1/1 | upstream `main` profile |
| zmk-feature-device-info | PASS | 3/3 | shared custom profile |
| zmk-feature-fast-keymap | BLOCKED | — | Required ZMK branch `pr/main+custom-studio-protocol/expose-stock-keymap` is absent on the remote |
| zmk-feature-input-stream | PASS | 3/3 | shared custom profile |
| zmk-feature-kscan-diagnostics | PASS | 4/4 | shared custom profile |
| zmk-feature-os-detection | PASS | 4/4 | custom profile with BLE management module |
| zmk-feature-runtime-combo | FAIL | 1/4 | shared custom profile; `array_max_size` API error |
| zmk-feature-runtime-macro | PASS | 5/5 | shared custom profile |
| zmk-feature-studio-rpc-perf | PASS | 3/3 | custom profile with BLE management module |
| zmk-feature-watchdog | PASS | 4/4 | shared custom profile |
| zmk-feature-zephyr-setting-expose | PASS | 3/3 | shared custom profile |
| zmk-keyboard-dya2 | PASS | 5/5 | DYA2 `main` profile |
| zmk-module-devtool | PASS | 3/3 | shared custom profile |
| zmk-module-iqs9150 | BLOCKED | — | No local `main` or `origin/main` ref |
| zmk-module-runtime-input-processor | PASS | 3/3 | shared custom profile |
| zmk-module-settings-rpc | PASS | 2/2 | `v0.3` activity profile |
| zmk-module-template-with-custom-studio-rpc | BLOCKED | — | No local `main` or `origin/main` ref |
| zmk-pmw3610-driver | PASS (integration) | DYA2 5/5 | No standalone West manifest or build target; its local `main` SHA is exactly the installed DYA2 dependency SHA |

## Failures and limits

- The PMW3610 RPC driver failed in `pmw3610_settings_rpc` and
  `pmw3610_settings_rpc_dual` at `src/settings/pmw3610_settings.c:195`:
  `struct zmk_custom_setting` has no `temp_slot` member.
- Runtime combo failed its three enabled targets at
  `src/runtime_combo/runtime_combo.c:57`: the same struct has no
  `array_max_size` member. Its feature-disabled target passed.
- Both modules built against the shared profile's
  `zmk-feature-custom-settings` commit `c6a7fef3…`, which is the remote
  `main` HEAD. The local `main` checkout is `d2eca675…`; changing the shared
  dependency would affect other worktrees, so this run kept the profile fixed.
- `zmk-feature-codex` requires an exact ZMK SHA, while this workspace's
  profile naming and placement policy uses ZMK branch names. The fast-keymap
  branch named by its local `main` manifest could not be fetched. The two
  repositories with no local `main` also had no `origin/main`; another branch
  was not substituted.
- No hardware test was run. A PASS here means the listed build command
  completed, or, for the manifest-less PMW3610 driver, that DYA2 built using
  the exact same source commit.

## Profile setup observations

New profiles were created for DYA2, upstream ZMK `main`, the two `v0.3`
branches, and the custom branch with BLE management. The profile initializer
now re-resolves imported projects after checking out the requested ZMK branch;
this was necessary because upstream `main` imports a different
`zmk-studio-messages` repository than the seed checkout. When more than one
profile satisfies a module's declarations, `shared_west.py worktree --profile`
selects the intended dependency baseline and still verifies compatibility.
