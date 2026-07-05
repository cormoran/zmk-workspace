---
name: develop-zmk-module
description: Develop a ZMK module with custom Studio RPC + web UI from cormoran's zmk-module-template-with-custom-studio-rpc inside this workspace. Use when creating a new ZMK module (driver, feature, or behavior) that needs runtime settings via zmk-feature-custom-settings, a custom Studio RPC subsystem, streaming/chunked RPC data transfer, or a WebSerial web UI, and when orchestrating the work across subagents with hardware validation.
---

# Develop a ZMK Module (custom Studio RPC template)

## Setup

Clone the template as the new module repo and use the **isolated** west layout
so each module clone is its own west topdir:

```bash
git clone https://github.com/cormoran/zmk-module-template-with-custom-studio-rpc <module-name>
cd <module-name>   # default branch is main+custom-studio-protocol
git checkout -b <impl-branch>
nix --extra-experimental-features 'nix-command flakes' develop /path/to/zmk-workspace/nix \
  --command bash -lc 'west init -l west --mf west-test-isolated.yml && west update --narrow && west zephyr-export'
```

Dependencies land in `./dependencies/` (ZMK fork `cormoran/zmk` branch
`main+custom-studio-protocol`, `zmk-feature-custom-settings`,
`zmk-west-commands`). Read the repo's `AGENTS.md` (init checklist, nanopb
rules) and keep `DESIGN.md` in the repo as the phase-by-phase source of truth.

## Orchestration pattern that works

Design first (write DESIGN.md), then delegate implementation phases to
subagents with self-contained prompts, verifying between phases:

- Phase A: template placeholder init + core sources import + build skeleton
- Phase B: settings + driver/feature APIs + RPC handlers (proto → firmware)
- Phase C: streaming features + web UI
- Phase D: hardware flash + RPC validation (build on `$build-zmk-config`
  and `$debug-zmk-jlink`)

Each phase prompt must include: exact nix devshell command line, test commands,
"commit at milestones, no push/gh", and the known pitfalls below. Hardware
phases (D) must additionally include the hardware-lock rule verbatim: acquire
per-device locks with the workspace's `tools/hw-lock` before any command that
touches a probe/board, heartbeat while holding, release when hardware work
ends (see `docs/hardware-locking.md` in the workspace repo).

## Commands

```bash
# inside nix devshell, repo root
python3 -m unittest            # build tests (tests/zmk-config) + native_sim tests
west zmk-build tests/zmk-config -q
west zmk-test tests -m .
cd web && npm ci && npm run generate && npm test && npm run lint && npm run build
pre-commit run --all-files     # see pitfall about web hooks
```

## Known pitfalls (all hit in practice)

- **nanopb**: set `has_<field> = true` for every sub-message; never use 64-bit
  proto types (`CONFIG_ZMK_STUDIO` implies `NANOPB_WITHOUT_64BIT`).
- **RPC buffers**: defaults are tiny (RX 30 / TX 64). Custom settings needs
  `CONFIG_ZMK_STUDIO_RPC_RX_BUF_SIZE=128`; chunked/bytes responses need
  `CONFIG_ZMK_STUDIO_RPC_TX_BUF_SIZE` ≥ chunk + ~64 overhead (use a
  `BUILD_ASSERT`). Response data must live in static buffers — encoding runs
  after the handler returns, possibly multiple times.
- **Zero-device / native_sim**: make `ZMK_<MOD>_STUDIO_RPC` and
  `ZMK_<MOD>_CUSTOM_SETTINGS` depend only on `ZMK_STUDIO` /
  `ZMK_CUSTOM_SETTINGS` (not the driver), provide an API stub returning 0
  devices when the driver isn't compiled, and handle 0 devices in handlers.
  This lets native_sim unit tests cover RPC/settings without hardware DT nodes.
- **`ZMK_CUSTOM_SETTING_DEFINE` + `ZMK_CUSTOM_SETTING_RANGE_INT32` does not
  compile** (nested compound literals in a static initializer, C11 6.6p9,
  enforced by arm-zephyr-eabi-gcc). Define settings with
  `STRUCT_SECTION_ITERABLE(zmk_custom_setting, ...)` and plain designated
  initializers instead.
- **`RC()` macro clash in overlays**: `dt-bindings/zmk/modifiers.h` (pulled in
  by keymaps) defines 1-arg `RC(mods)` clobbering `matrix_transform.h`'s
  2-arg `RC(row,col)`. In snippet overlays that redefine a transform, add
  `#undef RC` + re-include `<dt-bindings/zmk/matrix_transform.h>` first.
- **tester_xiao shield** uses `xiao_d 0..10` for kscan — any overlay adding
  SPI/GPIO peripherals on those pins must shrink `&kscan0 { input-gpios = ... }`
  (and the matrix transform) to non-conflicting pins.
- **Settings boot ordering**: `settings_load()` runs from `main()` after all
  SYS_INIT levels and does NOT raise `zmk_custom_setting_changed`. Apply
  persisted settings from the driver's own (async, workqueue-delayed) configure
  step, and listen for `zmk_custom_setting_changed` for post-boot changes.
- **Test wiring via snippets**: put device overlays + configs for build tests
  in `tests/zmk-config/snippets/<name>/` (`snippet_root: .` in
  tests/zmk-config/zephyr/module.yml); `build.yaml` entries accept both
  `snippet:` (single) and `snippets:` (list) with zmk-west-commands.
- **pre-commit web hooks** (prettier/eslint/jest/web-build) fail inside the nix
  devshell (broken bundled Node). Run the same checks directly with npm and use
  `SKIP=prettier,eslint,jest,web-build pre-commit run --all-files` for the rest.
- **Web proto from a dependency module**: point `web/buf.gen.yaml` at the
  dependency's proto dir (e.g. `../dependencies/zmk-feature-custom-settings/proto`)
  instead of vendoring into the repo's own `proto/` — the firmware nanopb glob
  would otherwise generate duplicate symbols.
- The generic settings web/RPC subsystem identifier is
  `cormoran_custom_settings`; module settings only need
  `ZMK_CUSTOM_SETTING`-style registry entries and a changed-event listener.

## Hardware validation

Use `$debug-zmk-jlink`. The rig is shared between concurrent agents — lock the
devices you use via the workspace's `tools/hw-lock` before touching them
(protocol: `docs/hardware-locking.md` in the workspace repo). Extra facts for
this workspace's rig:
[references/hardware-rig.md](references/hardware-rig.md).
