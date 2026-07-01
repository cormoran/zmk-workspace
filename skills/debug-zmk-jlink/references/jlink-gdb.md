# J-Link And GDB Notes

## Tool Discovery

Check for SEGGER and Zephyr SDK tools:

```bash
command -v JLinkExe JLinkGDBServerCLExe JLinkGDBServerExe JLinkRTTClient JLinkRTTLogger
command -v arm-zephyr-eabi-gdb gdb-multiarch
find /nix/store -path '*arm-zephyr-eabi-gdb' -o -path '*arm-zephyr-eabi-nm' 2>/dev/null | head
```

If `arm-zephyr-eabi-gdb` is not on PATH but the Zephyr SDK path appears in `build_info.yml`, use that absolute binary.

## LXC USB Notes

In LXC, bind the whole USB bus into the container, not a single `/dev/bus/usb/BBB/DDD` node. J-Link can re-enumerate during firmware update or reconnect, changing from IDs such as `1366:1061` to `1366:0101` and getting a new device number. If the new node is not visible inside the container, `ShowEmuList` may still list the probe but `Connect` or `JLinkGDBServerCLExe` fails with `Cannot connect to the probe/programmer`.

Useful checks:

```bash
lsusb
ls -l /dev/bus/usb/*/*
JLinkExe -NoGui 1 -CommandFile /tmp/jlink-show-emulators.jlink
```

For Proxmox/LXC, the host config usually needs the USB character-device major and a bind mount for `/dev/bus/usb`:

```text
lxc.cgroup2.devices.allow: c 189:* rwm
lxc.mount.entry: /dev/bus/usb dev/bus/usb none bind,optional,create=dir
```

## Typical nRF52840 Session

GDB server:

```bash
JLinkGDBServerCLExe -device nRF52840_xxAA -if SWD -speed 4000 -port 2331 -swoport 2332 -telnetport 2333
```

Use `JLinkGDBServerCLExe` on Linux/headless hosts. If `JLinkGDBServerExe` fails with an X server error, it is the GUI launcher, not a target failure.

GDB:

```gdb
target remote :2331
monitor halt
monitor reset
load
monitor reset
continue
```

For freeze capture:

```gdb
monitor halt
info registers
bt
thread apply all bt
info symbol $pc
x/16i $pc-16
```

Avoid `monitor reset` until the halted state is captured.

## Useful Breakpoints

Set only a few at a time:

```gdb
b k_panic
b z_fatal_error
b z_check_thread_stack_fail
b studio_framing_process_byte
b zmk_rpc_get_rx_buf
b zmk_rpc_get_tx_buf
b raise_zmk_studio_rpc_notification
b zmk_studio_core_lock
b zmk_studio_core_unlock
```

For custom subsystem bugs, locate handler names with:

```bash
arm-zephyr-eabi-nm -n zephyr/zmk.elf | rg 'custom|studio|runtime|handler'
```

Then break on the specific handler and response encoder.

## RTT And Logs

If RTT logging is enabled in the debug build, run:

```bash
JLinkRTTClient
```

or:

```bash
JLinkRTTLogger -Device nRF52840_xxAA -If SWD -Speed 4000 -RTTChannel 0 logs/rtt.log
```

If RTT is not enabled, use USB serial logs or enable a temporary Zephyr logging backend. Avoid consuming the same CDC ACM port with both logs and Studio RPC unless the build exposes separate interfaces.

## Thread And Stack Inspection

Best results require:

```text
CONFIG_THREAD_MONITOR=y
CONFIG_THREAD_NAME=y
CONFIG_THREAD_ANALYZER=y
CONFIG_INIT_STACKS=y
CONFIG_STACK_USAGE=y
CONFIG_DEBUG_THREAD_INFO=y
CONFIG_ASSERT=y
```

If GDB thread awareness is unavailable, use symbols and Zephyr globals:

```gdb
p/x _current
p *_current
info variables _k_thread
```

Use thread analyzer logs when possible; raw stack scanning from GDB is fragile unless stacks were initialized with a known fill pattern.

## Fault Capture

For ARM Cortex-M faults, capture core registers and fault status registers:

```gdb
info registers
p/x *(uint32_t*)0xE000ED28
p/x *(uint32_t*)0xE000ED2C
p/x *(uint32_t*)0xE000ED30
p/x *(uint32_t*)0xE000ED34
p/x *(uint32_t*)0xE000ED38
```

Then resolve PC/LR:

```gdb
info symbol $pc
info symbol $lr
bt
```
