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
