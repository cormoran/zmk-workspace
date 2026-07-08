# Reusable Renode CI for ZMK modules

Goal: any ZMK module repo (starting with
`zmk-module-template-with-custom-studio-rpc`) gets a CI job that boots its
built firmware in Renode and exercises real functionality (boot banner, core
Studio RPC, the module's own custom RPC) — with the *smallest possible
footprint in the module repo*. All heavy lifting lives here in
`zmk-workspace`, exposed as a reusable composite GitHub Action.

**IMPORTANT (2026-07-08 rework):** the reusable action does **not** build
firmware. Building a firmware ELF from a module repo's own sources is
squarely that module's own build flow's job (its own board/shield/config
choices, its own `build.yaml`) — the action's only job is to take an
already-built ELF and exercise it under Renode. See "Split of
responsibilities" below for the corrected shape; this obsoletes the earlier
`build_fw.py`-in-the-action design (`build_fw.py` itself still exists, for
local/skill use, but is no longer invoked by the action).

## Split of responsibilities

**zmk-workspace** (this repo) provides:

- A root-level Zephyr module (`zephyr/module.yml`,
  `name: zmk-workspace-renode-testing`) that any consumer picks up for free
  by adding this repo as a (test-only) west dependency: it registers the
  Renode-only Studio RPC UART transport
  (`skills/test-zmk-renode/renode-test-module/`, via `build.cmake`/
  `build.kconfig`) and a `snippet_root`
  (`skills/test-zmk-renode/snippets/`) so the module's own `west build`/
  `build.yaml` can apply the `renode-studio-uart` snippet directly — no
  `ZMK_EXTRA_MODULES` wiring or action-side build step needed. The
  `renode-test-module/` directory also keeps its own nested
  `zephyr/module.yml` for the older standalone-`ZMK_EXTRA_MODULES` pattern
  (still used by `build_fw.py`'s local/skill-compat role builds); the two
  don't conflict since west's module auto-discovery only looks at a west
  *project's* root, never recurses into subdirectories for more
  `module.yml` files.
- `skills/test-zmk-renode/snippets/renode-studio-uart/` — a Zephyr snippet
  (`snippet.yml` + `.conf` + `.overlay`, modeled on ZMK's own
  `studio-rpc-usb-uart` snippet) carrying exactly what `build_fw.py`'s
  `COMMON_ARGS`/`STUDIO_TRANSPORT_ARGS` used to set via raw cmake args:
  USB/BLE off, console/log on a real UART, the Renode-only transport
  enabled. nRF52840/XIAO-specific (see the overlay's own header comment).
- `.github/actions/zmk-renode-test/action.yml` — composite action, **test
  only**. When a workflow does
  `uses: cormoran/zmk-workspace/.github/actions/zmk-renode-test@<ref>`,
  GitHub downloads this whole repo at `<ref>` and `${{ github.action_path }}`
  points at the action dir — so the action can reference the skill's assets
  (`skills/test-zmk-renode/{platforms,scripts}`) by relative path. Single
  source of truth, no copying.
- Generalized scripts (refactored from the skill, which keeps working):
  - `scripts/renode_harness.py` — importable library: RenodeSession /
    MonitorConnection / wait_for_text / RpcSocket re-export / studio proto
    loading / renode install discovery. Module test files import this.
  - `scripts/build_fw.py` — still exists for local/skill use (the skill's
    own regression gate, ad-hoc local Renode builds) but the action no
    longer calls it.

Action contract (current):

```yaml
inputs:
  west-topdir:            # default "." -- only used to locate the caller's west deps for proto compilation
  elf-path:                # required -- path to the ALREADY-BUILT firmware ELF
  tests:                    # optional dir of module-specific unittest files (run with harness on PYTHONPATH)
  renode-version:          # default 1.16.1
  boot-timeout-seconds:     # default 20
```

Steps: cache + install Renode portable → pip deps (protobuf) → resolve +
validate `elf-path` (fails fast if missing -- the action does NOT build it)
→ run the generic smoke suite (boot banner + core GetDeviceInfo round-trip,
asserting a non-empty device name) → run the module's own `tests` dir if
given, with `ZMK_RENODE_ELF`, `RENODE`, and `PYTHONPATH` exported.

**Module repo (template)** provides:

- A `renode_smoke_test` (or similarly-named) artifact in its own
  `tests/zmk-config/build.yaml`, built with the `renode-studio-uart`
  snippet, as part of its normal build step (`python3 -m unittest` /
  `west zmk-build`) -- this IS "the build" the action used to do.
- `zmk-workspace` added to its **test-only** west manifest
  (`west/west-dependency/west-test-dependency.yml`), pinned by commit SHA,
  so the snippet + transport module above are available.
- One step (not a whole separate job) in `.github/workflows/zmk-module.yml`,
  after the build step, calling the action with `elf-path` pointing at the
  artifact's `zephyr/zmk.elf`.
- `tests/renode/renode_test.py` — small, exemplary, module-specific: send the
  template's own custom RPC (`your_name__template` SampleRequest) and assert
  the decoded SampleResponse. This is the part a template user rewrites for
  their module.
- Guide docs (README + AGENTS.md) explaining the flow and how to extend it.

## Implementation status (2026-07-08, superseded same day -- see rework note below)

Implemented as designed, with the details below refined during bring-up:

- `scripts/renode_harness.py`, generalized `scripts/build_fw.py` (both
  `--role` skill-compat and generic `--west-topdir`/`--board`/... modes),
  and `scripts/renode_smoke.py` all exist and are used by both this skill's
  own regression suite and the action.
- `.github/actions/zmk-renode-test/action.yml` implements the contract
  below almost exactly as drafted; see that directory's `README.md` for the
  final input list (added `west-topdir`, `zmk-app`, `boot-timeout-seconds`;
  `elf-path` supports the two-job fallback). One practical gotcha not
  anticipated below: the action's `module-paths`/`cmake-args` inputs must
  be passed to `build_fw.py` as `--flag=value` (not `--flag value`) since
  cmake args start with `-D`, which argparse otherwise misparses as a new
  flag.
- The template repo's `renode-test` CI job runs as a **single job** in
  `zmkfirmware/zmk-build-arm:stable` (the container has `protoc`
  installable via `apt-get` and Renode's portable Linux bundle ran fine
  headless with `--disable-xwt`) — the two-job `elf-path` fallback was not
  needed.

### Rework (2026-07-08, later same day): action no longer builds firmware

Repo-owner feedback: the reusable action must not build firmware — a
module's own build flow already knows how to build its own firmware and
should keep owning that; the action's job is strictly to test an
already-built ELF under Renode. Changed:

- Added a root-level `zephyr/module.yml` to this repo (`zephyr/module.yml`,
  see "Split of responsibilities" above) exposing the Renode transport
  module + a new `snippets/renode-studio-uart/` snippet as a normal Zephyr
  module any consumer's own `west build`/`build.yaml` can use directly.
- `action.yml`: removed `board`/`shield`/`zmk-config`/`zmk-app`/
  `module-paths`/`cmake-args`/`overlay` inputs and the "Build firmware"
  step entirely; `elf-path` is now **required** and validated (the action
  fails fast with a clear error if the path doesn't exist, rather than
  silently trying to build something).
- `build_fw.py` itself was deliberately left alone (not rewired to use the
  new snippet) — it remains in use by the skill's own local regression
  gate (`renode_test.py`, role-based builds against a sibling workspace
  that does not have zmk-workspace as a west dependency) and there was no
  need to touch a working, independently-tested path for this rework.
- Template-side: the whole separate `renode-test` job was deleted; a
  `renode_smoke_test` artifact was added to the template's own
  `build.yaml` (built via the `renode-studio-uart` snippet as part of the
  existing `python3 -m unittest` build step), and a single new step calling
  the reworked action with `elf-path` was added to the existing `Build`
  job. See the template repo's own `CLAUDE.md`/`AGENTS.md` and README for
  the resulting local repro commands.
- **Deviation from "the module's own custom RPC round trip, asserting the
  expected SampleResponse value":** bringing up the template's own
  `tests/renode/renode_test.py` hit a reproducible **Renode-environment**
  limitation — custom-subsystem responses larger than a few tens of bytes
  (the template's `SampleResponse` is ~51 B framed) are never delivered
  under Renode, and even small ones stall after a couple of round trips.
  A differential against `zmk-feature-studio-rpc-perf` (same fork commit
  618f083, same custom-subsystem macros, hardware-validated) reproduced
  the identical size-dependent stall under Renode, so this is emulation-
  specific, not a fork bug (an earlier draft of this note wrongly called
  it one). The template's test therefore asserts the custom-subsystem
  *envelope and dispatch* work end-to-end (via a call to a deliberately-
  invalid subsystem index, which takes a small, callback-free
  `meta.simple_error` path) and documents+asserts the known Renode stall
  for the real round trip, rather than asserting a real `SampleResponse`.
  See that test file's module docstring and this skill's `SKILL.md`
  ("Known Renode limitation") for the full differential data.

## Constraints / knowns

- The skill's own `renode_test.py` must stay green after any refactor here
  (regression gate: `python skills/test-zmk-renode/scripts/renode_test.py -v`).
- The template uses the patched ZMK (`main+custom-studio-protocol`); the
  transport clone in `renode-test-module/` must compile against it too.
- CI runner: prefer a single job inside `zmkfirmware/zmk-build-arm:stable`
  (west build needs the Zephyr toolchain) so the same job both builds the
  Renode artifact and can run Renode itself. If the Renode portable bundle
  can't run in that container, build in that job, upload the ELF as an
  artifact, and call this action from a second (plain `ubuntu-latest`) job
  with `elf-path` set after downloading it — the action still supports
  this two-job shape, it just never builds anything itself either way.
- Pin the action ref (and the `zmk-workspace` west manifest revision) in the
  module repo by commit SHA (immutable; valid even before the
  zmk-workspace PR merges, still valid after) — TODO: repoint both to
  `main` once the zmk-workspace PR merges.
