---
name: build-zmk-config
description: Build, test, and debug ZMK config repositories using this repo's Nix-based Zephyr/ZMK west workspace. Use when Codex needs to clone or initialize a zmk-config, choose the correct west workspace layout, interpret build.yaml, build firmware with west zmk-build or manually assembled west build commands, enable debug snippets such as zmk-usb-logging or studio-rpc-usb-uart, verify generated .uf2 artifacts, or diagnose ZMK build failures.
---

# Build ZMK Config

## Workflow

Use this workspace's Nix devShell for all west commands:

```bash
nix --extra-experimental-features 'nix-command flakes' develop /path/to/zmk-workspace/nix --command bash -lc '<commands>'
```

For a project under this `zmk-workspace`, read `$shared-west-profiles`
before setup. Place a project worktree in a compatible profile with
`tools/shared_west.py`; the profile is the West topdir and the worktree owns
its build directory. Read `references/west-layouts.md` for config manifests
and the standalone fallback outside a supported shared profile.

## Initialize

Clone a config under `projects/<repo>` and resolve its complete test manifest.
When the helper supports that manifest, use:

```bash
python3 tools/shared_west.py find <repo> --manifest config/<complete-manifest>.yml
python3 tools/shared_west.py worktree <repo> <branch> \
  --manifest config/<complete-manifest>.yml --profile <profile> --task '<task>'
```

Run those commands from the `zmk-workspace` root. If no compatible profile
exists, follow `$shared-west-profiles` to provision one from initialized
standalone dependencies. Some official-style configs have a different
manifest layout that `shared_west.py` cannot yet resolve; report that limit
instead of running `west init` or `west update` inside a shared worktree.

From the created worktree, verify the selected workspace and ZMK checkout:

```bash
west topdir
west list zmk -f '{abspath}'
```

## Choose Build Method

In the selected profile, choose the build method from the workspace:

- Use `west zmk-build` when the manifest imports `zmk-west-commands` or `west help zmk-build` works. This command understands `build.yaml`.
- Use manual `west build` when `zmk-build` is unavailable, including the official unified template.

With `zmk-build`:

```bash
west zmk-build -d ./build -q
west zmk-build -d ./build -q -S zmk-usb-logging
```

Without `zmk-build`, build each target from `build.yaml` yourself. Locate the ZMK app from west instead of assuming a fixed path:

```bash
zmk_app="$(west list zmk -f '{abspath}')/app"
west build -s "$zmk_app" -d "build/<artifact>" -b "<board>" [ -S "<snippet>" ] -- \
  -DSHIELD="<shield>" \
  -DZMK_CONFIG="$(pwd)/config" \
  <cmake-args>
```

Important details:
- `-s "$zmk_app"` is required when the current directory is only a config repo and has no `CMakeLists.txt`.
- Omit `-DSHIELD` when the build target has no shield.
- Put Zephyr snippets before `--`; put CMake arguments after `--`.
- Use a distinct `-d` directory per target.
- Use `-p always` only when intentionally rebuilding an existing build directory from scratch.

## Expand build.yaml

Read `build.yaml` before building:

- Top-level `board: [...]` and `shield: [...]` form a Cartesian product.
- Top-level `include:` entries are explicit targets and can add `snippet`, `cmake-args`, `artifact`, or `artifact-name`.
- Prefer `artifact-name` or `artifact` for the build directory name when present; otherwise use `<board>__<shield>` or `<board>`.
- Keep both `artifact` and `artifact-name` in mind because different templates and helpers use different spellings.

Example for the official unified template after enabling:

```yaml
board: [ "nice_nano" ]
shield: [ "corne_left", "corne_right" ]
```

Manual commands:

```bash
zmk_app="$(west list zmk -f '{abspath}')/app"
west build -s "$zmk_app" -d build/nice_nano__corne_left -b nice_nano -- \
  -DSHIELD=corne_left \
  -DZMK_CONFIG="$(pwd)/config"
west build -s "$zmk_app" -d build/nice_nano__corne_right -b nice_nano -- \
  -DSHIELD=corne_right \
  -DZMK_CONFIG="$(pwd)/config"
```

## Validation

A build is successful only after every expected target finishes and every expected firmware artifact exists:

```bash
find <build-dir> -type f -path '*/zephyr/zmk.uf2' -print
```

For `west zmk-build`, compare the target count printed from `build.yaml` with the number of generated `.uf2` files. For manual builds, check each target's build directory.

When tests are requested, run repository tests that exist in addition to firmware builds:
- `python -m unittest` for zmk modules or configs with Python tests
- `west twister` only when the config/module provides Zephyr tests and the needed platform is clear

For native-sim snapshot suites run `west zmk-test` as well. A successful
build or a `PASS:` line in the generated log is not by itself a test oracle:
inspect the case's `events.patterns` and paired `*.snapshot`, add the new
stable expected line to both when behavior changes, then re-run the suite.
Review the filtered output before accepting a snapshot update; snapshots must
assert the feature's observable result, not incidental logging.

Report exact target names, board/shield/snippet values, artifact paths, and the first actionable CMake/Kconfig/devicetree error when a build fails.
