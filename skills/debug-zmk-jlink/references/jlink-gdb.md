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
JLinkRTTLogger -Device nRF52840_xxAA -If SWD -Speed 4000 -USB <serial> -RTTAddress <addr> -RTTChannel 0 logs/rtt.log
```

If RTT is not enabled, use USB serial logs or enable a temporary Zephyr logging backend. Avoid consuming the same CDC ACM port with both logs and Studio RPC unless the build exposes separate interfaces.

**Confirmed failure mode (2026-07-07): `JLinkRTTLogger` can reliably report
`RTT Control Block not found` even when the control block genuinely exists
at the address given via `-RTTAddress`** (verified independently by reading
the same address with a raw `mem`/`savebin` and seeing the `"SEGGER RTT"`
magic string right there). This happened consistently in one environment
regardless of `-USB`/`-SelectEmuBySN`, explicit vs. auto-searched address,
or target run/halt state — treat `JLinkRTTLogger`/`JLinkRTTClient` as
"try first, but don't block on it," and fall back to manually polling the
RTT buffer via plain memory reads (below) if it won't attach.

### Non-halting memory reads (critical for BLE/radio-timing-sensitive targets)

`JLinkExe`'s `mem`/`mem32`/`savebin` commands do **not** require halting the
core first — Cortex-M's AHB-AP supports background memory access while the
CPU keeps running. Use `connect` (not `h`/`halt`) before them:

```text
SelectEmuBySN <serial>
device NRF52840_XXAA
si SWD
speed 4000
connect
savebin out.bin 0x20000000 0x100
mem32 0xE000EDF0, 1
qc
```

This matters a lot on targets running a Zephyr **software** BLE Link Layer
(`CONFIG_BT_LL_SW_SPLIT`) — its radio-event-prepare callbacks run under an
extremely tight timing budget, and halting the core (via GDB attach, or via
plain `h` in a JLinkExe script) even briefly can trip
`LL_ASSERT_OVERHEAD`-class assertions and reset/crash the target. A
sustained GDB `continue` session attached to such a target measurably
increased crash rates in one investigation (60-100% vs. 0% hands-off across
40+ trials) — see `skills/debug-zmk-split/SKILL.md`'s "GDB Attach Itself Can
Destabilize BLE Radio Timing" section for the full writeup. Prefer
`connect`+`mem`/`savebin` (no halt at all) or, if a halt is unavoidable, the
shortest possible `h` → `mem`/`savebin`/`regs` → `g` round-trip over a held
breakpoint or a live `continue`-based GDB session.

Also note: on these software-LL targets, `CONFIG_LOG_MODE_IMMEDIATE` fails
to even **compile** (`BUILD_ASSERT`: *"Immediate logging on selected
backend(s) not supported with the software Link Layer"*) — use
`CONFIG_LOG_MODE_DEFERRED` (the default) if adding a logging backend for
diagnostics on such a board.

### Manually parsing the RTT control block

When `JLinkRTTLogger` won't attach, read `_SEGGER_RTT` directly. Get its
address (shifts per build — re-derive every time):

```bash
arm-zephyr-eabi-nm zephyr/zmk.elf | grep '_SEGGER_RTT\b'
```

Layout (`struct SEGGER_RTT_CB`, little-endian, 32-bit fields):

| Offset | Field | Size |
|---|---|---|
| `0x00` | `acID` (`"SEGGER RTT\0..."`) | 16 bytes |
| `0x10` | `MaxNumUpBuffers` | 4 |
| `0x14` | `MaxNumDownBuffers` | 4 |
| `0x18` | `aUp[0].sName` (pointer) | 4 |
| `0x1C` | `aUp[0].pBuffer` (pointer) | 4 |
| `0x20` | `aUp[0].SizeOfBuffer` | 4 |
| `0x24` | `aUp[0].WrOff` | 4 |
| `0x28` | `aUp[0].RdOff` | 4 |
| `0x2C` | `aUp[0].Flags` | 4 |

(`aUp[1]`, `aUp[2]`, ... and then `aDown[]` follow at `+0x18` increments if
`MaxNumUpBuffers`/`MaxNumDownBuffers` > 1.) Read the control block, then
`pBuffer` for the actual text, decoding only up to `WrOff` (bytes past it
are stale leftovers, not valid data — the buffer does not zero-fill):

```bash
JLinkExe -CommanderScript - <<'EOF'
SelectEmuBySN <serial>
device NRF52840_XXAA
si SWD
speed 4000
connect
savebin ctrl.bin <_SEGGER_RTT addr> 0x30
qc
EOF
python3 -c "
import struct
d = open('ctrl.bin','rb').read()
pbuf, size, wroff, rdoff = struct.unpack_from('<IIII', d, 0x1C)
print(f'pBuffer=0x{pbuf:x} size={size} WrOff={wroff} RdOff={rdoff}')
"
# then savebin the buffer at pBuffer for size bytes, and decode data[:WrOff]
```

`RdOff` only advances when something actually reads and acks the buffer
(a real RTT client, not this manual technique) — with no client attached
it just stays wherever it last was (0 on a fresh boot). Comparing `WrOff`
across successive non-halting polls (without ever resetting the target) is
a reliable way to tell "still producing output" from "stalled/hung"
without touching the core at all; cross-check with DHCSR (below) before
concluding a target is truly stuck.

### Checking core run/halt/lockup state without halting

`DHCSR` (`0xE000EDF0`) can be read the same non-invasive way and tells you
whether the core is actually running, without ever halting it:

```text
mem32 0xE000EDF0, 1
```

Bit meanings on read: bit 17 `S_HALT`, bit 18 `S_SLEEP` (in WFI/WFE — normal
for an idle RTOS thread), bit 19 `S_LOCKUP`, bit 24 `S_RETIRE_ST` (at least
one instruction retired since the *previous* read of this register — sticky,
clears on read). Reading twice a couple seconds apart and seeing
`S_RETIRE_ST` stay `0` both times, with `S_HALT`/`S_LOCKUP` also `0`, is a
strong non-invasive signal the target is genuinely stuck (e.g. blocked
forever in a `k_sem_take(K_FOREVER)` or similar) rather than just idling —
confirmed useful for diagnosing a BLE-init hang without ever touching the
core with a halt.

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
