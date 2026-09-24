---
name: debug-zmk-jlink
description: Debug ZMK keyboard firmware on hardware with J-Link plus ZMK Studio RPC. Use when investigating freezes, lockups, stack headroom, logging, runtime behavior, Studio custom subsystems, USB/BLE Studio transport issues, or verifying that a ZMK board built by build-zmk-config behaves as expected under real device interaction and debugger inspection.
---

# Debug ZMK With J-Link

## Operating Model

Use this skill for hardware-in-the-loop ZMK debugging. Use `$build-zmk-config` when the target repo has a matching ZMK config/build definition; for a standalone ZMK fixture, build with `west` and record the equivalent board, shield, config, and artifact paths. Then use the repository's Studio RPC documentation and helper tools to exercise firmware behavior, with J-Link/GDB attached when RPC, logs, stack evidence, or USB/BLE behavior indicate a fault.

Prefer the least intrusive observation first:

1. Build through the matching config workflow or `west`, then audit generated config, ELF, map, and logs.
2. Flash and collect serial/RTT logs.
3. Use Studio RPC to query device info, lock state, custom subsystem list, and target subsystem calls.
4. If the firmware freezes or behaves suspiciously, halt with J-Link and inspect threads, stacks, registers, backtrace, and relevant symbols.
5. Rebuild with temporary debug Kconfig only when runtime evidence is insufficient, and keep a near-release build for comparison.

## Subagent Model Recommendation

Delegate bounded J-Link work to `gpt-6-luna` when subagents are available and the user permits delegation. Use `medium` reasoning effort for an end-to-end preflight, build, flash, and verification task; use `low` for a narrowly specified readout or app-only flash when the probe/board mapping, image, address range, and success checks are already known. Give the worker the skill path, exact target/probe identity if known, hardware lock requirement, intended artifact, and required evidence; make one worker own the hardware at a time. Escalate uncertain board identification, damaged UICR/bootloader, protected SWD, or full-chip recovery planning to `gpt-6-sol` at `medium` before destructive writes.

This recommendation is based on two 2026-09-23 XIAO trials: Luna at `low` completed a normal `0x27000` build, J-Link flash/readback, and USB verification; a second independent Luna `low` pass completed a read-only preflight from the revised skill. The first run initially stopped on an unrelated invalid lock-list entry and needed explicit guidance to lock only the probe while the XIAO had no USB identity. Thus `low` is proven for bounded hardware steps, while `medium` is the safer recommendation for the full workflow; the latter has not yet been measured here. OpenAI's [model selection guide](https://developers.openai.com/api/docs/guides/model-selection) also places Luna on scoped tasks and recommends comparing effort on representative work.

## Lock the Hardware First

The rig is shared by concurrent agent sessions. Before the first command that touches a probe or board — `JLinkExe` (even `ShowEmuList`), `JLinkGDBServer*`, flashing, RTT, or opening `/dev/zmk-hp-*` for Studio RPC — acquire per-device locks, and release them the moment hardware work ends. Full protocol (resource names, heartbeat, staleness, owner id rules): `docs/hardware-locking.md` in this workspace.

```bash
SID=<your-session-id-or-worktree-name>   # same value on every call, whole session
"$ZMK_WORKSPACE"/tools/hw-lock list      # resources: jlink-<serial>, zmk-<serial>
"$ZMK_WORKSPACE"/tools/hw-lock acquire --owner "$SID" --task "<goal>" jlink-<serial> zmk-<serial>
"$ZMK_WORKSPACE"/tools/hw-lock touch --owner "$SID" jlink-<serial> zmk-<serial>   # heartbeat: before each hardware batch, ≥ every 3 min
"$ZMK_WORKSPACE"/tools/hw-lock release --owner "$SID" --all                       # when hardware work ends
```

Lock the probe together with the `zmk-<serial>` of the board it is SWD-wired to (flash/halt/reset disturbs the board's USB side). If you don't yet know which serials form your unit, acquire everything (`acquire $(hw-lock list --names)`) and release the extras after identification. If `acquire` reports another live owner, retry with `--wait <sec>`, do non-hardware work, or report the contention — never touch the hardware without holding the lock.

If the XIAO currently has **no USB identity** (for example, its application does not enumerate), lock its J-Link probe first and acquire the board's `zmk-<serial>` lock as soon as USB enumeration supplies one. Do not treat an unrelated `/dev/zmk-hp-zmk-input-*` node as the XIAO merely because `hw-lock list` includes it. On this rig, an input-only node can yield a synthetic serial containing `:` that `hw-lock acquire` rejects; this does not prevent locking the J-Link probe itself.

## Required Setup

Invoke `$build-zmk-config` when the project has a matching config; otherwise use its documented `west` build workflow for the available fixture. Keep the build log, `.config`, `build_info.yml` when generated, `zephyr/zmk.elf`, `zephyr/zmk.map`, and generated UF2/HEX. If the repo provides a Nix devShell for west, use it.

Check tools before interacting with hardware:

```bash
command -v JLinkExe JLinkGDBServerCLExe JLinkGDBServerExe JLinkRTTClient JLinkRTTLogger
command -v arm-zephyr-eabi-gdb gdb-multiarch
command -v python3 protoc
python3 -c 'import serial, grpc_tools.protoc, google.protobuf'
lsusb | grep -i 'SEGGER\|J-Link'
```

Treat J-Link probe presence and SEGGER CLI availability as separate facts. A probe can appear in USB as `1366:* SEGGER J-Link` while `JLinkExe` and `JLinkGDBServerExe` are absent from PATH or unavailable inside the current container. In that case, report "probe visible, SEGGER tools unavailable" and either add the SEGGER tools to PATH/container or use an available libjaylink-based tool only if it supports the needed debugging workflow.

For XIAO BLE / nRF52840 targets, the J-Link device is usually `nRF52840_xxAA`, interface `SWD`, speed `4000`. Confirm the MCU from `build_info.yml` before using these defaults.

## XIAO nRF52840 Boot-Chain Preflight

Before flashing or treating missing USB/RPC as an application bug, read [references/xiao-nrf52840-recovery.md](references/xiao-nrf52840-recovery.md). With the hardware lock held, identify the exact board and probe, confirm an nRF52840 Cortex-M4 and target voltage, then inspect the reset vectors, UICR bootloader address, application link address, and bootloader/SoftDevice presence. Preserve a flash/UICR backup before changing a suspect boot chain. The reference gives a decision table for a working factory-style chain, stale code at `0x0`, missing SoftDevice/MBR, damaged bootloader, wrong UICR, and access/connection failures.

Before using USB absence as evidence that the boot chain is broken, check the flashed build's `.config`: `CONFIG_ZMK_USB=y` and the intended USB transport must be enabled if USB enumeration or Studio RPC over USB is expected. A correctly running ZMK image with `CONFIG_ZMK_USB` unset may have no USB identity.

USB CDC enumeration alone does not prove Studio RPC is enabled. Before probing RPC, confirm `CONFIG_ZMK_STUDIO=y` and the appropriate Studio transport in the build config. If the running image's ELF/config is unavailable, record its provenance as unknown; vectors and USB descriptors can establish that code is running but cannot establish its Kconfig or expected RPC behavior.

Prefer restoring only the damaged layer to the Seeed XIAO layout (`MBR + S140` below `0x27000`, application at `0x27000`, bootloader at `0xF4000`, bootloader settings near `0xFD800`, UICR pointing to `0xF4000`). Use the exact XIAO variant's Seeed combined HEX when restoring MBR/SoftDevice/bootloader; its `nosd` UF2 update does not repair a missing SoftDevice. Do not use a `code_partition`-at-`0x0` overlay as the routine fix for a broken boot chain: that bypasses the bootloader and leaves the next normal ZMK build broken. For a known working boot chain, flash only the application HEX at its verified partition address. Verify the target runs and enumerates after every recovery step before beginning firmware debugging.

## XIAO BLE DAP Power-Up Failure

When a XIAO BLE is SWD-wired to J-Link and `JLinkExe` reports `Found SW-DP` followed by `Failed to power up DAP`, first confirm that the probe sees the target reference voltage and can read the SW-DP ID. This failure can occur when the J-Link was powered before the XIAO was connected to USB.

Power-cycle the **J-Link probe** while leaving the XIAO connected to the PC, then retry the SWD connection. This restored a XIAO BLE / nRF52840 where J-Link reset, low-speed SWD, and target RESET did not. Do not erase or recover the target merely to address this symptom.

For normal setup, connect the XIAO to the PC before powering or attaching the J-Link.

## Build Audit

Run the audit helper after `$build-zmk-config`:

```bash
python3 <skill>/scripts/zmk_debug_audit.py --build-dir build/abyss_tester_xiao_studio
```

Inspect especially:

- `CONFIG_ZMK_STUDIO=y`, one Studio transport enabled, and the intended Studio snippet in `build_info.yml`.
- Stack-related Kconfig: `CONFIG_ZMK_STUDIO_RPC_THREAD_STACK_SIZE`, `CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE`, `CONFIG_MAIN_STACK_SIZE`, `CONFIG_ISR_STACK_SIZE`, `CONFIG_INPUT_THREAD_STACK_SIZE`, `CONFIG_ZMK_LOW_PRIORITY_THREAD_STACK_SIZE`.
- Debug observability: `CONFIG_THREAD_MONITOR`, `CONFIG_THREAD_NAME`, `CONFIG_THREAD_ANALYZER`, `CONFIG_INIT_STACKS`, `CONFIG_STACK_USAGE`, `CONFIG_ASSERT`, logging backend, RTT, shell.
- Memory summary from the build log or map.
- Warnings in `stdout_and_stderr.log`, especially Studio custom subsystem, nanopb, stack, buffer, or pointer warnings.

For deeper guidance, read [references/zmk-debug-checklist.md](references/zmk-debug-checklist.md).

## Studio RPC

Read the project RPC doc first. Prefer `docs/zmk-studio-rpc.md` if present in the user's repo; otherwise read ZMK's upstream `docs/docs/development/studio-rpc-protocol.md` in the checked-out ZMK dependency. Then inspect the local proto files under `dependencies/modules/msgs/zmk-studio-messages/proto/zmk` and any module-owned custom subsystem proto files.

In this workspace, prefer the documented CLI:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc --workspace "$ZMK_WORKSPACE" list-ports
PYTHONPATH=tools tools/zmk-studio-rpc --workspace "$ZMK_WORKSPACE" --port "$PORT" info
PYTHONPATH=tools tools/zmk-studio-rpc --workspace "$ZMK_WORKSPACE" --port "$PORT" lock-state
PYTHONPATH=tools tools/zmk-studio-rpc --workspace "$ZMK_WORKSPACE" --port "$PORT" custom-list
PYTHONPATH=tools tools/zmk-studio-rpc --workspace "$ZMK_WORKSPACE" --port "$PORT" probe
```

For builds with `cormoran__devtool`, use benign devtool calls to inspect and unlock Studio before secured requests:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc --workspace "$ZMK_WORKSPACE" --port "$PORT" devtool get-lock-state
PYTHONPATH=tools tools/zmk-studio-rpc --workspace "$ZMK_WORKSPACE" --port "$PORT" devtool unlock
```

Use the bundled low-level RPC helper only when the repo CLI is unavailable or when framed hex/dry-run output is useful:

```bash
python3 <skill>/scripts/zmk_studio_rpc_probe.py \
  --port /dev/ttyACM0 \
  --proto-dir dependencies/modules/msgs/zmk-studio-messages/proto/zmk \
  --device-info --lock-state --list-custom --read-notifications 2
```

Use `--dry-run` with the same request flags to verify protobuf generation and framing without opening the serial port.

Exercise firmware deliberately and timestamp each request:

- Query `core.get_device_info` to verify framing, protobuf decoding, and transport.
- Query `core.get_lock_state`; if locked, unlock from the keyboard behavior or an available devtool custom subsystem before testing writes.
- Query `custom.list_custom_subsystems`; note subsystem identifiers and indexes because indexes are build/runtime specific.
- Send custom calls only after reading the target subsystem proto or C handler; keep payloads below `CONFIG_ZMK_STUDIO_RPC_CUSTOM_SUBSYSTEM_REQUEST_PAYLOAD_MAX_BYTES`.
- Repeat benign requests while watching logs and J-Link state to reproduce freezes with timestamps.
- Avoid destructive calls such as reset settings, reboot, bootloader, or writing persistent settings unless the user explicitly wants that experiment.

For protocol details and examples, read [references/studio-rpc.md](references/studio-rpc.md).

## J-Link Debugging

Generate helper files from the ELF:

```bash
python3 <skill>/scripts/jlink_debug_files.py \
  --build-dir build/abyss_tester_xiao_studio \
  --device nRF52840_xxAA
```

Start a GDB server:

```bash
JLinkGDBServerCLExe -device nRF52840_xxAA -if SWD -speed 4000 -port 2331 -swoport 2332 -telnetport 2333
```

On Linux/headless environments, prefer `JLinkGDBServerCLExe`. `JLinkGDBServerExe` may require an X server even for simple help/version output.

When more than one J-Link probe is attached (e.g. debugging two boards of a split keyboard at once), always select the probe explicitly instead of relying on default/first-found selection. List probes and their serials first:

```bash
printf 'ShowEmuList\nExit\n' > /tmp/jlink-show-emulators.jlink
JLinkExe -NoGui 1 -CommandFile /tmp/jlink-show-emulators.jlink
```

Then pin each `JLinkExe`/`JLinkGDBServerCLExe` invocation to one probe by serial, and give each GDB server instance its own port set so both can run concurrently:

```bash
JLinkExe -USB <serial> -NoGui 1 -CommandFile <file>          # or SelectEmuBySN <serial> inside the command file
JLinkGDBServerCLExe -USB <serial-a> -device nRF52840_xxAA -if SWD -speed 4000 -port 2331 -swoport 2332 -telnetport 2333
JLinkGDBServerCLExe -USB <serial-b> -device nRF52840_xxAA -if SWD -speed 4000 -port 2341 -swoport 2342 -telnetport 2343
```

If a probe is listed by `ShowEmuList` but every command against it fails with `Cannot connect to the probe/programmer`, its raw USB device node is likely missing from the container (see `references/jlink-gdb.md`'s LXC USB Notes) — this is an environment/pass-through problem, not a wiring or firmware problem.

Connect:

```bash
arm-zephyr-eabi-gdb build/abyss_tester_xiao_studio/zephyr/zmk.elf \
  -x build/abyss_tester_xiao_studio/jlink/zmk-jlink.gdbinit
```

When a freeze occurs, avoid resetting first. Halt and capture:

```gdb
monitor halt
info registers
bt
thread apply all bt
p/x _current
info symbol $pc
```

Then inspect likely ZMK/Studio paths:

```gdb
b zmk_rpc_get_rx_buf
b zmk_rpc_get_tx_buf
b studio_framing_process_byte
b zmk_studio_core_lock
b zmk_studio_core_unlock
b z_check_thread_stack_fail
b k_panic
```

For J-Link command details, RTT logging, and freeze triage, read [references/jlink-gdb.md](references/jlink-gdb.md).

**On BLE/radio-timing-sensitive targets (a Zephyr software Link Layer,
`CONFIG_BT_LL_SW_SPLIT`), prefer non-halting observation.** Halting the
core — via a held GDB breakpoint/`continue` session, or even a plain
JLinkExe `h`/`halt` — can itself trip radio-timing assertions and
crash/reset the target, contaminating the exact behavior being
investigated. `JLinkExe`'s `mem`/`savebin` commands work without halting
(`connect` then read, no `h`) via Cortex-M's background memory access —
use this to poll RTT logs or core-status registers (`DHCSR`) non-invasively
instead of a live GDB session whenever the target's own radio/BLE timing
is a live concern. See references/jlink-gdb.md's "Non-halting memory
reads" section for the exact recipe, and
`.agents/skills/debug-zmk-split/SKILL.md`'s "GDB Attach Itself Can Destabilize BLE
Radio Timing" section for the hardware evidence behind this guidance.

**Before attributing a "response/output never arrives" symptom to
timing, transport, or connection issues, rule out leftover diagnostic
scaffolding in the suspect code first.** A `printk`/`LOG_*` immediately
followed by an early `return`/`break` — left over from an earlier
debugging session and never reverted — produces exactly this symptom and
is invisible to any amount of hardware tracing, because the traced layer
(transport/connection) was never actually broken; the handler simply
never reached its real logic. `grep` the suspect handler(s) for such
scaffolding (watch for comments like "DIAG STEP", "bisecting", "revert
before committing") before spending hardware time on deeper hypotheses.

## Stack Headroom Strategy

Do not declare stack sizes safe from configured sizes alone. Establish evidence in this order:

1. Enable temporary observability if absent: `CONFIG_INIT_STACKS=y`, `CONFIG_THREAD_MONITOR=y`, `CONFIG_THREAD_NAME=y`, `CONFIG_THREAD_ANALYZER=y`, `CONFIG_STACK_USAGE=y`, `CONFIG_ASSERT=y`, and a log backend usable on the target.
2. Rebuild with `$build-zmk-config` and reflash.
3. Exercise Studio RPC, custom subsystems, key scanning, pointing, combos/macros, and lock/unlock paths.
4. Collect thread analyzer output or GDB-visible stack usage while the device is idle, under RPC load, and immediately after the suspected freeze.
5. Treat less than about 25-30% free stack on recurring workloads as suspicious for keyboard firmware with feature-heavy Studio custom subsystems.

If debug Kconfig changes alter timing or memory enough to hide the bug, keep a second build close to release settings and use J-Link halt/backtrace plus targeted breakpoints.

## Report Shape

Return a concise debugging report with:

- Build identity: board, shield, snippet, artifact, git revision if available, ELF path.
- What was exercised over Studio RPC and what responses/notifications were observed.
- Logs and warnings that matter.
- J-Link findings: halt location, backtrace, current thread, breakpoints hit, fault registers if any.
- Stack/memory headroom evidence.
- Next firmware change or experiment, scoped to the observed failure.
