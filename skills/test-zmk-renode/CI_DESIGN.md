# Reusable Renode CI for ZMK modules

Goal: any ZMK module repo (starting with
`zmk-module-template-with-custom-studio-rpc`) gets a CI job that boots its
built firmware in Renode and exercises real functionality (boot banner, core
Studio RPC, the module's own custom RPC) — with the *smallest possible
footprint in the module repo*. All heavy lifting lives here in
`zmk-workspace`, exposed as a reusable composite GitHub Action.

## Split of responsibilities

**zmk-workspace** (this repo) provides:

- `.github/actions/zmk-renode-test/action.yml` — composite action. When a
  workflow does `uses: cormoran/zmk-workspace/.github/actions/zmk-renode-test@<ref>`,
  GitHub downloads this whole repo at `<ref>` and `${{ github.action_path }}`
  points at the action dir — so the action can reference the skill's assets
  (`skills/test-zmk-renode/{overlays,platforms,renode-test-module,scripts}`)
  by relative path. Single source of truth, no copying.
- Generalized scripts (refactored from the skill, which keeps working):
  - `scripts/renode_harness.py` — importable library: RenodeSession /
    MonitorConnection / wait_for_text / RpcSocket re-export / studio proto
    loading / renode install discovery. Module test files import this.
  - `scripts/build_fw.py` — parameterized (board, shield, zmk-config dir,
    extra modules, extra cmake args, west topdir) instead of hardcoded to the
    studio-rpc-perf workspace.

Action contract (approximate — refine during bring-up):

```yaml
inputs:
  board:            # default xiao_ble//zmk (the only bring-up-validated board)
  shield:           # e.g. tester_xiao
  zmk-config:       # path to the module's tests/zmk-config/config
  module-paths:     # extra ZMK_EXTRA_MODULES entries (the module repo itself, its tests/zmk-config, ...)
  cmake-args:       # module feature flags, e.g. -DCONFIG_ZMK_TEMPLATE_FEATURE=y ...
  tests:            # optional dir of module-specific unittest files (run with harness on PYTHONPATH)
  renode-version:   # default 1.16.1
```

Steps: cache + install Renode portable → pip deps (protobuf/grpcio-tools) →
build ELF via the generalized `build_fw.py` (adds the Renode UART transport
module + overlay + the usual USB/QSPI/BLE-off config automatically) → run the
generic smoke suite (boot banner + core GetDeviceInfo round-trip, asserting a
non-empty device name) → run the module's own `tests` dir if given, with
`ZMK_RENODE_ELF`, `RENODE`, and `PYTHONPATH` exported.

**Module repo (template)** provides only:

- One extra job in `.github/workflows/zmk-module.yml` calling the action
  (west init via the repo's existing local `west-init` action first).
- `tests/renode/test_renode.py` — small, exemplary, module-specific: send the
  template's own custom RPC (`your_name__template` SampleRequest) and assert
  the decoded SampleResponse. This is the part a template user rewrites for
  their module.
- Guide docs (README + AGENTS.md) explaining the flow and how to extend it.

## Constraints / knowns

- The skill's own `renode_test.py` must stay green after the refactor
  (regression gate: `python skills/test-zmk-renode/scripts/renode_test.py -v`).
- The template uses the patched ZMK (`main+custom-studio-protocol`); the
  transport clone in `renode-test-module/` must compile against it too.
- CI runner: prefer a single job inside `zmkfirmware/zmk-build-arm:stable`
  (west build needs the Zephyr toolchain). If the Renode portable bundle
  can't run in that container, fall back to two jobs (build in container →
  upload ELF → run Renode on plain `ubuntu-latest`); the action should accept
  a prebuilt `elf-path` to support that shape.
- Pin the action ref in the module repo by commit SHA (immutable; valid even
  before the zmk-workspace PR merges, still valid after).
