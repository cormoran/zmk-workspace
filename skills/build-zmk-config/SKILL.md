---
name: build-zmk-config
description: Build, test, and debug ZMK config repositories using this repo's Nix-based Zephyr/ZMK west workspace. Use when Codex needs to clone or initialize a zmk-config, choose the correct west workspace layout, run west update/zephyr-export, build firmware with west zmk-build or west build, enable debug snippets such as zmk-usb-logging, verify generated .uf2 artifacts, or diagnose ZMK build failures.
---

# Build ZMK Config

## Core Workflow

Prefer the clone-root layout for parallel work: clone each zmk-config into its own directory, make that clone the west topdir, and keep dependencies under that clone. Use the repository-root layout only when the config explicitly expects the surrounding zmk-workspace directory to be the west topdir.

Use this workspace's Nix devShell for every west command:

```bash
nix --extra-experimental-features 'nix-command flakes' develop /path/to/zmk-workspace/nix --command <command>
```

If the environment already enables nix-command/flakes, the extra flag is harmless. If sandboxing blocks `~/.cache/nix`, set `XDG_CACHE_HOME=/tmp/nix-cache`; otherwise use the normal cache.

## Fast Path

Use the bundled helper for the common clone-root flow:

```bash
skills/build-zmk-config/scripts/build_zmk_config.sh \
  --repo https://github.com/owner/zmk-config.git \
  --workdir .work
```

For an already-cloned config:

```bash
skills/build-zmk-config/scripts/build_zmk_config.sh \
  --config-dir /path/to/zmk-config
```

Pass extra `west zmk-build` flags after `--`, for example:

```bash
skills/build-zmk-config/scripts/build_zmk_config.sh \
  --config-dir /path/to/zmk-config \
  -- -S zmk-usb-logging
```

The helper intentionally targets configs that provide `zmk-west-commands` and `build.yaml`. If `west zmk-build` is not available, use the manual fallback below.

## Layout Decision

Read `references/west-layouts.md` when the manifest layout is unclear.

Clone-root indicators:
- `config/west-isolated.yml`
- `config/west.yml` importing `west-isolated.yml`
- README or CI uses `west init -l config` or `west init -l config --mf west-isolated.yml`
- Dependencies are expected under `<config-repo>/dependencies`

Repository-root indicators:
- README for this zmk-workspace says `west init -m <config-repo> --mf <manifest>`
- The config only provides a root manifest or `config/west-workspace.yml`
- Dependencies are expected as siblings of the config repo

Be careful: `cd <config-repo> && west init -l . --mf config/west-workspace.yml` can create `.west` in the parent directory, not in the clone. Do not use it when the requested layout is clone-root.

## Manual Clone-Root Build

For configs like `cormoran/zmk-keyboard-abyss-tester-xiao`:

```bash
git clone https://github.com/cormoran/zmk-keyboard-abyss-tester-xiao.git .work/zmk-keyboard-abyss-tester-xiao
cd .work/zmk-keyboard-abyss-tester-xiao
nix --extra-experimental-features 'nix-command flakes' develop /path/to/zmk-workspace/nix --command bash -lc '
  west init -l config --mf west-isolated.yml
  west update --narrow
  west zephyr-export
  west zmk-build -d ./build -q
'
```

Verify:

```bash
west topdir
find build -type f -path '*/zephyr/zmk.uf2' -print
```

`west topdir` must be the cloned config directory for clone-root builds.

## Manual Fallback Without zmk-build

For official-style configs without `zmk-west-commands`, read `build.yaml` and run one `west build` per board/shield entry:

```bash
west build -d build/<artifact-name> -b <board> -- \
  -DSHIELD=<shield> \
  -DZMK_CONFIG="$(pwd)/config" \
  <cmake-args>
```

If an entry has `snippet`, add `-S <snippet>` before `--`. If it has no shield, omit `-DSHIELD`.

## Validation

A build is successful only after all expected targets finish and every expected firmware artifact exists. For `west zmk-build`, count the targets reported from `build.yaml` and verify matching `build/*/zephyr/zmk.uf2` files.

When the user asks for tests, run repository tests that exist in addition to firmware builds:
- `python -m unittest` for zmk modules or configs with Python tests
- `west twister` only when the config/module provides Zephyr tests and the needed platform is clear
- this skill's own validation with `quick_validate.py` after editing the skill

Report exact failing target names, board/shield/snippet values, and the first actionable CMake/Kconfig/devicetree error.
