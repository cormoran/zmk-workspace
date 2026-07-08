---
name: test-zmk-renode
description: Test a ZMK keyboard for the XIAO nRF52840 (Studio RPC + split) inside the Renode emulator, with no physical hardware. Use when verifying Studio RPC or split-keyboard behavior without a real board/J-Link rig, when CI or a sandboxed environment has no hardware access, or when iterating on ZMK/Studio RPC firmware changes and you want a fast, repeatable, hardware-free feedback loop before (or instead of) a real-hardware session with $debug-zmk-jlink/$debug-zmk-split.
---

# Test ZMK In Renode (XIAO nRF52840, Studio RPC + Split)

## What This Actually Emulates

Renode is a functional (not cycle-accurate) full-system emulator. It runs
the exact same ARM `.elf` that would run on real XIAO nRF52840 silicon —
same Zephyr, same ZMK, same RPC/split C code, no source changes needed
for the two tiers that are green. What's substituted:

- **Studio RPC "over USB" → Studio RPC over a real hardware UART.**
  Renode's nRF52840 USBD peripheral is a non-functional SVD-register
  stub (real hardware sets `EVENTCAUSE.READY` a few µs after `ENABLE`,
  as part of USB PHY power-up, unrelated to a host being attached;
  Renode's stub never does) — `usb_enable()` hangs forever before
  `main()`, unconditionally, regardless of USB class (HID, CDC-ACM,
  whatever). USB is simply not usable under this Renode nRF52840 model,
  full stop. The RPC *byte framing on the wire* is identical either way
  (see `dependencies/zmk/app/src/studio/uart_rpc_transport.c`); only the
  physical carrier changes, and — see below — how the transport gets
  *selected* had to change too.
- **Split over BLE → split over wired UART.** Two Renode machines, one
  `emulation CreateUARTHub`, each machine's UART1 connected to it — a
  genuine point-to-point link, confirmed with a real cross-machine event
  relay (see T2 below).
- **Everything else is real**: real ARM Cortex-M4 execution, real ZMK
  keymap/kscan/RPC/split C code, real nanopb-encoded protobuf messages
  parsed by the actual firmware.

## Tier Matrix

| Tier | What | Status |
|------|------|--------|
| T0 | Boot a single board, see the real ZMK banner on console UART | GREEN |
| T1 | Studio RPC over UART round-trips a real, correctly-decoded protobuf response | GREEN (must-pass, confirmed robust across multiple sequential requests) |
| T2 | Wired split: central receives + applies a peripheral-originated key event over the split-wired UART link | GREEN |
| T3 | BLE (Studio-over-BLE and/or split-over-BLE) | Experimental, gated off by default — see below |

Run everything: `python skills/test-zmk-renode/scripts/renode_test.py -v`
(~100s). All green plus one documented skip is the expected/normal result.

## Setup

Install Renode (portable tarball, no system mono/dotnet needed):

```bash
bash skills/test-zmk-renode/scripts/install_renode.sh
```

`scripts/renode_test.py` also auto-installs Renode on first run if it's
missing, so this step is optional in practice.

## Running The Tests

```bash
cd skills/test-zmk-renode/scripts
python renode_test.py -v                        # everything
python renode_test.py -v RenodeZmkTests.test_t1_studio_rpc_uart
python -m unittest renode_test -v                # equivalent, module form
```

Non-zero exit on any failure (standard `unittest` behavior) — safe to wire
into CI. Firmware is (re)built automatically via `scripts/build_fw.py`
(wraps `west build` with the exact flags this write-up documents); builds
are cached under `zmk-feature-studio-rpc-perf/build/renode_*` and only
rebuilt when the underlying overlay/module/Kconfig actually changes (west's
own incremental build, `-p auto`).

To build a single artifact by hand (e.g. to boot it interactively and poke
around):

```bash
python skills/test-zmk-renode/scripts/build_fw.py --role single
python skills/test-zmk-renode/scripts/build_fw.py --role central
python skills/test-zmk-renode/scripts/build_fw.py --role peripheral
```

## T3 (BLE) — What We Know, Deliberately Not Pursued Further

A single board with `CONFIG_ZMK_BLE=y` and *no peer at all* reliably hits
a kernel oops ~10s after boot (`bt_settings: settings_subsys_init failed
(err -33)` → `BLUETOOTH FAILED (-33)` → an HCI command timeout assertion
→ `ZEPHYR FATAL ERROR`). This happens before any split/Studio-over-BLE
logic is even reachable. Renode's own bundled Zephyr BLE examples use the
same radio peripheral successfully, so this looks like a ZMK-specific
settings/controller-bringup interaction under Renode rather than "BLE is
unusable in Renode" categorically — but per the mission's explicit time-box
on T3, this was not chased further.

`test_t3_ble_single_board_boot` reproduces and asserts this exact failure
signature (skipped by default; `RENODE_ZMK_RUN_T3=1` to run it) so a future
session has a concrete, automated starting point instead of rediscovering
it from scratch.

## Reusable Renode CI Action (for other module repos)

This skill's harness is also exposed as a reusable composite GitHub Action,
`.github/actions/zmk-renode-test/`, so any ZMK module repo can boot its own
firmware in Renode and run its own tests in CI without depending on this
skill's specific workspace layout. See that directory's README for the
inputs/usage snippet, and `scripts/renode_harness.py` /
`scripts/renode_smoke.py` / `scripts/build_fw.py`'s generic (non-`--role`)
mode for the importable/parameterized pieces the action wires together.
`zmk-module-template-with-custom-studio-rpc`'s `tests/renode/` is the
worked example.

### Known Renode limitation: larger custom-subsystem RPC responses stall

Bringing up `zmk-module-template-with-custom-studio-rpc`'s own
`tests/renode/renode_test.py` (exercising its custom Studio RPC subsystem,
not just core RPC) surfaced a reproducible **Renode-environment**
limitation. Initially this looked like a general bug in the vendored
"custom-studio-protocol" ZMK fork, but a differential against
`zmk-feature-studio-rpc-perf` — which uses the exact same custom-subsystem
macros, is pinned to the *same* fork commit (618f083), and is validated
working on real hardware — showed the perf module's custom RPC hits the
same wall under Renode. So: Renode-specific, not a fork bug. Measured
scaling (all under Renode, fresh boot per case):

| Response | ~framed size | Result under Renode |
|---|---|---|
| `meta.simple_error` (invalid subsystem index) | ~10 B | reliable, repeatedly |
| core `GetDeviceInfo` (the smoke test) | ~21 B | reliable, repeatedly (T1 sends 2) |
| perf custom response, `response_size=8` | ~28 B | OK twice, 3rd call times out |
| perf custom response, `response_size=40/64` | ~55–90 B | first call times out |
| template `SampleResponse` | ~51 B | first call times out |
| `ListCustomSubsystemRequest` (identifier + UI URL) | ~80+ B | first call times out |

During a stall the firmware is *not* crashed — `sysbus.cpu
ExecutedInstructions` keeps growing steadily and `sysbus.cpu PC` samples
land inside `ring_buf_area_claim`/`ring_buf_area_finish` — consistent with
the studio RPC TX path waiting on a TX ring buffer that never drains.
Ruled out individually: request-delivery timing (byte-paced sends behave
identically), `CONFIG_ZMK_STUDIO_RPC_RX_BUF_SIZE` (30 vs 128),
`CONFIG_ZMK_STUDIO_RPC_TX_BUF_SIZE` (64 vs 256, verified in `.config`),
and always-enabling TX IRQ in `renode-test-module`'s transport. The most
plausible remaining suspect is an interaction between `rpc.c`'s
`tx_notify` batching heuristics and Renode's nRF52840 UARTE TX-interrupt
model; not chased further per time-box (it does not affect real hardware).

Practical rule for tests running under this harness: **keep RPC responses
small (≲25 bytes framed) and don't rely on more than a couple of
custom-subsystem round trips per boot** — or assert the documented failure,
as the template's `..._KNOWN_BROKEN_UNDER_RENODE` test does, so a future
fix announces itself. See that test file's module docstring for the full
differential write-up.

## Key Gotchas (see `references/renode-notes.md` for the full detail)

1. **QSPI and USB must both be disabled in the devicetree overlay, not just
   Kconfig.** Both are SVD-register-stub peripherals in Renode with a
   driver init that busy-waits forever on an event the stub never sets —
   an unconditional, silent (no crash, no log) hang before `main()`.
   Disabling the *parent* devicetree node (`&qspi`, `&usbd`) is not
   enough; status doesn't cascade to children (`p25q16h`,
   `board_cdc_acm_uart`), so both must be disabled explicitly. See
   `overlays/*.overlay`.
2. **ZMK's UART Studio RPC transport is tagged `ZMK_TRANSPORT_USB` and
   gated behind a real, host-negotiated USB HID connection** —
   `zmk_endpoint_get_selected()` has to report USB before the transport's
   `rx_start()` ever gets called, regardless of what physical carrier
   backs it. Since USB is unconditionally broken here, that gate can never
   open. Fixed with `renode-test-module/` — a small additive Zephyr module
   (zero vendored ZMK changes) registering a second, otherwise-identical
   transport tagged `ZMK_TRANSPORT_NONE` (the natural state with USB+BLE
   both off and no persisted settings). Gated behind
   `CONFIG_ZMK_RENODE_STUDIO_UART_TRANSPORT` (default n) — **never enable
   this for a real hardware build.**
3. **TX interrupt storm**: neither ZMK's own UART RPC transport nor our
   copy originally disabled the TX IRQ once the send buffer drained. Under
   Renode this reads as a level-triggered condition that never clears with
   nothing queued, permanently starving the RPC processing thread after
   exactly one request/response. Our transport now explicitly disables TX
   IRQ on drain (a one-line, clearly-commented deviation from upstream).
4. **A Renode `CreateServerSocketTerminal` UART socket reliably serves
   exactly one client connection for the life of the process.**
   Reconnecting silently gets nothing, forever, on either read or write.
   Connect once per session and keep the socket open — `renode_test.py`'s
   `RenodeSession` is built around this.
5. **Split-wired-over-`CreateUARTHub` genuinely works** (cross-machine
   event relay confirmed via a monitor-injected GPIO toggle), but wait a
   couple of real seconds after `start` before relying on a cross-machine
   event in a test — synthetic boot-time kscan events on one machine can
   fire before the other machine's own `SYS_INIT`-time UART RX-enable has
   necessarily run, and get silently dropped (no cross-machine execution
   ordering guarantee at t=0).
6. **`west build` needs `-s dependencies/zmk/app`** (not the
   `zmk-feature-studio-rpc-perf` repo root, which is a Zephyr *module*
   manifest, not an application) plus explicit `ZEPHYR_TOOLCHAIN_VARIANT`/
   `ZEPHYR_SDK_INSTALL_DIR` (a stale CMake user-package-registry entry can
   otherwise point at a different project's Zephyr checkout entirely).

## Files In This Skill

```
DESIGN.md                 - the original bring-up plan (tiers, rationale)
EXPERIMENT_LOG.md          - chronological narrative of what was tried
references/renode-notes.md - distilled, reusable gotchas (read this first
                              if you're debugging a new hang/silence)
overlays/
  studio-rpc-uart.overlay  - T0/T1: console=uart0, Studio RPC=uart1, qspi+usb disabled
  split-wired-uart.overlay - T2: console=uart0, zmk,wired-split=uart1, qspi+usb disabled
platforms/
  xiao_nrf52840.repl       - checked-in copy of Renode's nRF52840 platform description
  single.resc              - T0/T1: one machine, two UART sockets (console, RPC)
  split_wired.resc         - T2: two machines, UART hub cross-connecting their split UARTs
renode-test-module/        - small additive Zephyr module: the ZMK_TRANSPORT_NONE
                              Studio RPC UART transport that makes T1 possible
                              without real USB (see gotcha #2 above)
scripts/
  install_renode.sh         - fetch Renode portable
  build_fw.py                - wraps `west build` with all the flags this doc explains
  renode_test.py             - the orchestrator/test suite (unittest-based)
  rpc_client.py               - Studio RPC framing over a TCP socket (reused, unmodified)
```

## Honesty Check

T0/T1/T2 are real, hardware-free, automated, and green — not fabricated.
T1 in particular is a genuine end-to-end proof: a Python client builds a
real protobuf `Request`, frames it per ZMK Studio's wire protocol, sends it
over a TCP socket that Renode bridges to an emulated UART peripheral, and
gets back a `Response` that the actual firmware's nanopb-based RPC
subsystem encoded — decoded values (`name: "MAK"`) match the real firmware
configuration, not a stub. T2 is a genuine cross-machine relay, not two
independent single-board runs. T3 is honestly incomplete: it documents a
real, reproducible failure rather than a passing capability, and says so.
