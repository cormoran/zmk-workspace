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

Prefer a clone-root west workspace for parallel work: clone each zmk-config into its own directory and make that clone the west topdir. Use a repository-root workspace only when the config or zmk-workspace instructions require it. Read `references/west-layouts.md` when the layout is unclear.

## Initialize

For clone-root configs with `config/west-isolated.yml`:

```bash
cd <zmk-config>
west init -l config --mf west-isolated.yml
west update --narrow
west zephyr-export
```

For official-style configs such as `zmkfirmware/unified-zmk-config-template`, where `config/west.yml` contains `self: path: config`:

```bash
cd <zmk-config>
west init -l config
west update --narrow
west zephyr-export
```

Verify clone-root initialization:

```bash
west topdir
```

It must print the cloned config directory.

## Choose Build Method

After `west update`, choose the build method from the workspace:

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
- this skill's own `quick_validate.py` after editing the skill

Report exact target names, board/shield/snippet values, artifact paths, and the first actionable CMake/Kconfig/devicetree error when a build fails.
