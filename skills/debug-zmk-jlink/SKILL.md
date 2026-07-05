---
name: debug-zmk-jlink
description: Debug ZMK keyboard firmware on hardware with J-Link plus ZMK Studio RPC. Use when investigating freezes, lockups, stack headroom, logging, runtime behavior, Studio custom subsystems, USB/BLE Studio transport issues, or verifying that a ZMK board built by build-zmk-config behaves as expected under real device interaction and debugger inspection.
---

# Debug ZMK With J-Link

## Operating Model

Use this skill for hardware-in-the-loop ZMK debugging. Always use `$build-zmk-config` for builds and rebuilds first. Then use the repository's Studio RPC documentation and helper tools to exercise firmware behavior, with J-Link/GDB attached when RPC, logs, stack evidence, or USB/BLE behavior indicate a fault.

Prefer the least intrusive observation first:

1. Build with `$build-zmk-config` and audit generated config, ELF, map, and logs.
2. Flash and collect serial/RTT logs.
3. Use Studio RPC to query device info, lock state, custom subsystem list, and target subsystem calls.
4. If the firmware freezes or behaves suspiciously, halt with J-Link and inspect threads, stacks, registers, backtrace, and relevant symbols.
5. Rebuild with temporary debug Kconfig only when runtime evidence is insufficient, and keep a near-release build for comparison.

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

## Required Setup

Invoke `$build-zmk-config` to produce a build directory and firmware artifacts. Keep the build log, `.config`, `build_info.yml`, `zephyr/zmk.elf`, `zephyr/zmk.map`, and generated UF2/HEX. If the repo provides a Nix devShell for west, run the build through that shell as described by `$build-zmk-config`.

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
