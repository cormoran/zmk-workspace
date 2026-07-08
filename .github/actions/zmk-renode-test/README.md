# zmk-renode-test

Reusable composite GitHub Action: boots an **already-built** ZMK module
firmware ELF in the [Renode](https://renode.io/) emulator, runs a generic
boot + core Studio RPC smoke test, and (optionally) the consuming module's
own Renode test suite. Backed by `skills/test-zmk-renode/` in this same
repo — read that skill's `SKILL.md` and `references/renode-notes.md` for the
gotchas this action's steps exist to work around (silent boot hangs,
one-client UART sockets, the USB-gated transport, etc.).

**This action does not build firmware.** The caller builds the
Renode-testable ELF itself, as a normal step in its own build flow (a
`build.yaml` artifact, most naturally), and passes the resulting ELF path
in via `elf-path`. This repo provides everything needed to build that ELF
as a Zephyr module + snippet — see "Building the Renode-testable ELF"
below.

## Building the Renode-testable ELF

Real hardware normally carries ZMK Studio RPC over USB-CDC-ACM. Renode's
nRF52840 USBD model is a non-functional register stub (see
`skills/test-zmk-renode/SKILL.md`), so a Renode-testable build needs:

- The `renode-studio-uart` snippet (nRF52840/XIAO-specific — binds console
  + Studio RPC to real UART peripherals instead of USB, and disables the
  DT nodes whose init busy-waits forever under Renode: `&usbd`, `&qspi`,
  `&p25q16h`).
- The Renode-only `ZMK_TRANSPORT_NONE` Studio RPC UART transport
  (`CONFIG_ZMK_RENODE_STUDIO_UART_TRANSPORT=y`), which the snippet's conf
  file enables automatically (it bypasses the real transport's USB-HID
  gate that Renode can never satisfy).

Both are shipped as **this repo's own root-level Zephyr module**
(`zephyr/module.yml`, `name: zmk-workspace-renode-testing`), so any
consumer that has `zmk-workspace` as a west dependency gets the snippet and
the transport module auto-discovered for free — no `ZMK_EXTRA_MODULES`
wiring needed. Add it as a **test-only** west dependency (do not pull it
into a module's real/published manifest), then build a normal artifact
with the snippet applied, e.g. in `build.yaml`:

```yaml
- artifact: renode_smoke_test
  board: xiao_ble//zmk
  shield: tester_xiao
  cmake-args: -DCONFIG_ZMK_STUDIO=y -DCONFIG_ZMK_TEMPLATE_FEATURE=y -DCONFIG_ZMK_TEMPLATE_FEATURE_STUDIO_RPC=y
  snippets:
    - renode-studio-uart
```

or directly with `west build -S renode-studio-uart ...` /
`west zmk-build <config> -S renode-studio-uart`. This produces a normal
`zephyr/zmk.elf` under the build directory — pass that path as `elf-path`
below.

## Usage

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 30 # building the extra Renode artifact + Renode itself takes longer than a plain build
    container:
      image: zmkfirmware/zmk-build-arm:stable
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/west-init  # your module's own west-init (must resolve the zmk-workspace test dependency)

      - name: Build (including the Renode-testable artifact)
        run: python3 -m unittest -v # or `west zmk-build ...` -- whatever already builds build.yaml's artifacts

      - uses: cormoran/zmk-workspace/.github/actions/zmk-renode-test@<sha>
        with:
          elf-path: build/renode_smoke_test/zephyr/zmk.elf
          tests: tests/renode
```

Pin `@<sha>` to a commit SHA on this repo (immutable, works even before any
PR into `zmk-workspace` merges). See
`zmk-module-template-with-custom-studio-rpc`'s
`.github/workflows/zmk-module.yml` for a complete, working example.

Path inputs may be relative; the action resolves them against
`$GITHUB_WORKSPACE` inside its own steps. **Prefer relative paths over
`${{ github.workspace }}`** — in a container job that expression evaluates
to the runner-host path (`/home/runner/work/...`) while the checkout is
mounted at `/__w/...` inside the container, so host-absolute paths do not
exist there (actions/runner#716).

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `west-topdir` | no | `.` (workspace root) | The consuming module's own west workspace root (its checkout root, for a module with an embedded workspace). Used only to locate the caller's west dependencies for compiling studio protos for the smoke test — **not** for building firmware. |
| `elf-path` | yes | — | Path to the already-built firmware ELF to test. The caller builds this (see "Building the Renode-testable ELF" above) in an earlier step. |
| `tests` | no | — | Path (relative to `west-topdir`) to a directory of the module's own Renode test files. Every `*_test.py` directly under it is run via `python3 <file> -v`. Leave empty to run only the generic smoke test. |
| `renode-version` | no | `1.16.1` | Renode portable release to install (cached across runs). |
| `boot-timeout-seconds` | no | `20` | Smoke test: seconds to wait for the ZMK boot banner. |

## Outputs

| Output | Description |
|---|---|
| `elf-path` | Absolute path to the (caller-built) firmware ELF, resolved from the `elf-path` input. |

## What the generic smoke test checks

Regardless of what the module does, the action always verifies, before
running any module-specific test:

1. The real ZMK boot banner (`Welcome to ZMK`) appears on the console UART.
2. A core Studio RPC `GetDeviceInfo` request round-trips a well-formed
   response with a non-empty device name.

This is the "does this thing even boot and speak Studio RPC" gate. A
module's own `tests/renode/*_test.py` files only need to cover what's
specific to that module (its own custom RPC subsystem, etc.) — they import
`renode_harness` (provided on `PYTHONPATH` by this action) for the shared
Renode/RPC plumbing and read the built ELF's path from `ZMK_RENODE_ELF`.

## Constraints

- The caller must build the ELF itself before calling this action (this
  action fails fast with a clear error if `elf-path` doesn't exist).
- Renode itself must be able to run in whatever job/container calls this
  action (this action installs + caches it there). If the container that
  builds firmware can't also run Renode, build in that job, upload the ELF
  as an artifact, and call this action from a second (plain `ubuntu-latest`)
  job after downloading it.
