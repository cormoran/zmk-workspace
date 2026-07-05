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

**Confirmed failure mode (2026-07-05, LXD container with 2 J-Links attached):**
`ShowEmuList` listing a probe does not guarantee it is actually reachable.
Cross-check with the container's own view before trusting `ShowEmuList`:

```bash
for d in /sys/bus/usb/devices/*; do
  [ -f "$d/idVendor" ] && [ "$(cat "$d/idVendor")" = "1366" ] && \
    echo "$d: product=$(cat "$d/idProduct") busnum=$(cat "$d/busnum") devnum=$(cat "$d/devnum") serial=$(cat "$d/serial" 2>/dev/null)"
done
stat "/dev/bus/usb/$(printf '%03d' "$busnum")/$(printf '%03d' "$devnum")"
```

If `stat` reports "No such file", the probe is enumerated in sysfs (which an
unprivileged container can usually read) but its raw usbfs device node was
never bind-mounted into the container's `/dev/bus/usb` — a per-device LXD
pass-through gap, not a JLinkExe problem. `SelectEmuBySN <serial>` then fails
with `Cannot connect to the probe/programmer` on every subsequent command in
the script, even non-connecting ones like `device`/`si`/`speed`. The fix is
host-side (add/repair the LXD `usb` device for that probe's vendor:product,
or restart the container); do not try to `mknod` the raw usbfs node
yourself from inside the container as a workaround — usbfs character
devices created that way do not behave like the real bind-mounted node and
a `JLinkExe` connect attempt against one can hang for minutes. Repeated
connect attempts against an unreachable probe have also been observed to
knock a *different, working* probe's USB descriptor into a recovery-looking
product ID (e.g. `1366:0101 "J-Link PLUS"` instead of its normal ID) —
if that happens, stop and ask for the probe to be power-cycled rather than
continuing to retry.

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
