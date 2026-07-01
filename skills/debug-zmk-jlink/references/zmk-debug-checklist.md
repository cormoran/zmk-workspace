# ZMK Debug Checklist

## Build Identity

Record:

- Repo path and git revision.
- Board, shield, snippet, artifact name.
- `west.command` and `west.topdir` from `build_info.yml`.
- ELF, map, `.config`, UF2/HEX paths.
- Zephyr version and toolchain path.

The `abyss_tester_xiao` sample used for this skill had:

- Board: `xiao_ble`
- Shield: `abyss_tester_xiao`
- Snippet: `studio-rpc-usb-uart`
- Studio enabled with USB UART transport.
- Studio RPC thread stack: 4096 bytes.
- RPC RX/TX buffers: 256 bytes.
- Custom subsystem max request payload: 192 bytes.
- Release-style observability was intentionally limited: logging, thread analyzer, stack usage, and assertions were not enabled in the verified build.
- Build memory summary was about 22% flash and 34% RAM used, leaving enough static memory headroom for a separate observability build.

## Kconfig To Inspect

Studio:

```text
CONFIG_ZMK_STUDIO
CONFIG_ZMK_STUDIO_LOCKING
CONFIG_ZMK_STUDIO_TRANSPORT_UART
CONFIG_ZMK_STUDIO_TRANSPORT_BLE
CONFIG_ZMK_STUDIO_RPC_THREAD_STACK_SIZE
CONFIG_ZMK_STUDIO_RPC_RX_BUF_SIZE
CONFIG_ZMK_STUDIO_RPC_TX_BUF_SIZE
CONFIG_ZMK_STUDIO_RPC_CUSTOM_SUBSYSTEM_REQUEST_PAYLOAD_MAX_BYTES
```

Stacks:

```text
CONFIG_MAIN_STACK_SIZE
CONFIG_ISR_STACK_SIZE
CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE
CONFIG_INPUT_THREAD_STACK_SIZE
CONFIG_ZMK_LOW_PRIORITY_THREAD_STACK_SIZE
CONFIG_USB_WORKQUEUE_STACK_SIZE
CONFIG_USB_NRFX_WORK_QUEUE_STACK_SIZE
```

Debug observability:

```text
CONFIG_ASSERT
CONFIG_INIT_STACKS
CONFIG_HW_STACK_PROTECTION
CONFIG_THREAD_STACK_INFO
CONFIG_THREAD_MONITOR
CONFIG_THREAD_NAME
CONFIG_THREAD_ANALYZER
CONFIG_STACK_USAGE
CONFIG_LOG
CONFIG_LOG_OUTPUT
CONFIG_USE_SEGGER_RTT
CONFIG_LOG_BACKEND_RTT
CONFIG_SHELL
```

Use a separate debug/observability build when these are absent. Keep the original build too, because enabling logs, stack sentinels, analyzers, or assertions can change timing and memory layout.

## Runtime Tests

Minimum:

- Boot without fault.
- Studio serial port appears.
- `core.get_device_info` responds.
- `core.get_lock_state` responds.
- `custom.list_custom_subsystems` returns expected identifiers.
- Lock/unlock transitions generate expected responses or notifications.
- If a devtool subsystem is available, `devtool get-lock-state` works before using `devtool unlock`.

Stress:

- Repeat benign RPC requests for several minutes.
- Exercise key scanning while RPC traffic is active.
- Exercise pointing, RGB/backlight, combos, macros, input processors, and custom settings if enabled.
- Disconnect/reconnect USB and BLE if both are relevant.
- Trigger settings saves and wait for debounce windows.

## Evidence Quality

Strong evidence:

- Reproducible RPC sequence with request ids and timestamps.
- Logs bracketing the failure.
- J-Link halt before reset with PC, LR, registers, and backtrace.
- Thread analyzer output under realistic load.
- Memory summary and stack high-water marks.
- Comparison between near-release firmware and observability firmware when enabling debug Kconfig changes behavior.

Weak evidence:

- "No crash after one boot."
- Configured stack sizes without runtime high-water marks.
- Reset logs after a freeze without the halted state.

## Common Findings

- Studio custom response exceeds TX buffer.
- Custom request payload exceeds configured max.
- Firmware is locked, so write-like Studio calls are rejected or ignored.
- USB CDC port is consumed by another process.
- Debug logging changes timing enough to hide a race.
- Stack margins are acceptable at idle but poor during RPC plus input events.
