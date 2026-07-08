# zmk-renode-test

Reusable composite GitHub Action: builds a ZMK module's firmware with the
Renode-only Studio-RPC-over-UART overlay + transport (real hardware uses
USB; Renode's USB model is a non-functional register stub, so testing under
emulation swaps in a wired-UART carrier with identical RPC framing), boots
it in the [Renode](https://renode.io/) emulator, runs a generic boot + core
Studio RPC smoke test, and (optionally) the consuming module's own Renode
test suite. Backed by `skills/test-zmk-renode/` in this same repo — read
that skill's `SKILL.md` and `references/renode-notes.md` for the gotchas
this action's steps exist to work around (silent boot hangs, one-client
UART sockets, the USB-gated transport, etc.).

## Usage

```yaml
jobs:
  renode-test:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    container:
      image: zmkfirmware/zmk-build-arm:stable
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/west-init  # your module's own west-init

      - uses: cormoran/zmk-workspace/.github/actions/zmk-renode-test@<sha>
        with:
          shield: tester_xiao
          zmk-config: tests/zmk-config/config
          module-paths: |
            .
            tests/zmk-config
          cmake-args: |
            -DCONFIG_ZMK_STUDIO=y
            -DCONFIG_ZMK_TEMPLATE_FEATURE=y
            -DCONFIG_ZMK_TEMPLATE_FEATURE_STUDIO_RPC=y
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
| `west-topdir` | no | `.` (workspace root) | The consuming module's own west workspace root (its checkout root, for a module with an embedded workspace). |
| `board` | no | `xiao_ble//zmk` | Target board triplet. The only bring-up-validated board. |
| `shield` | yes | — | Shield to build (`-DSHIELD=...`). |
| `zmk-config` | yes | — | Path to the `ZMK_CONFIG` dir. |
| `zmk-app` | no | `<west-topdir>/dependencies/zmk/app` | Override the `-s` app dir. |
| `module-paths` | no | — | Extra `ZMK_EXTRA_MODULES` entries, one per line. The Renode transport module is always appended automatically. |
| `cmake-args` | no | — | Extra `-D...` cmake args, one per line. `CONFIG_ZMK_STUDIO=y` is **not** implied — include it if Studio RPC is needed. |
| `overlay` | no | `studio-rpc-uart` | `studio-rpc-uart`, `split-wired-uart`, or a path (relative to `west-topdir`) to a custom overlay. |
| `elf-path` | no | — | Skip the build step and test this prebuilt ELF instead (for a two-job build→artifact→test split if Renode can't run in your build container). |
| `tests` | no | — | Path (relative to `west-topdir`) to a directory of the module's own Renode test files. Every `*_test.py` directly under it is run via `python3 <file> -v`. Leave empty to run only the generic smoke test. |
| `renode-version` | no | `1.16.1` | Renode portable release to install (cached across runs). |
| `boot-timeout-seconds` | no | `20` | Smoke test: seconds to wait for the ZMK boot banner. |

## Outputs

| Output | Description |
|---|---|
| `elf-path` | Absolute path to the (built or prebuilt) firmware ELF, for a later step to upload as an artifact etc. |

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

- Runs `west build`, so it needs the Zephyr toolchain — run it in a
  container with that available (e.g. `zmkfirmware/zmk-build-arm:stable`),
  after your module's own west-init step.
- If Renode itself can't run in that same container (missing shared libs),
  build in one job, `actions/upload-artifact`/`download-artifact` the ELF,
  and call this action in a second (plain `ubuntu-latest`) job with
  `elf-path` set and no build inputs needed.
