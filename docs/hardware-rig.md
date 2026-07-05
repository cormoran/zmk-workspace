# cormoran's hardware rig

This describes the physical + host setup used to validate ZMK modules/features
in this workspace on real hardware, so it can be reproduced (roughly) by
someone else or on a new machine. It intentionally omits machine-specific
details (IP addresses, MAC addresses, serial numbers) — those are recorded
privately alongside the actual host, not here.

## Physical hardware

- 2x [Seeed XIAO nRF52840 (Sense)](https://wiki.seeedstudio.com/XIAO_BLE/)
  boards used as generic test boards for whichever module/feature is being
  worked on. One of them additionally has a PMW3610 optical sensor wired to
  it for trackball/sensor driver work (see [pmw3610.md](pmw3610.md)).
- 2x SEGGER J-Link probes, each with its SWD lines wired to one of the two
  XIAO boards (SWDIO/SWCLK/GND — no reset line needed, `AIRCR.SYSRESETREQ`
  via `JLinkExe`'s `r` command is used instead). Having two independent
  probes is what makes it possible to flash and observe two boards at once
  (e.g. to validate a ZMK split keyboard's central + peripheral roles
  pairing with each other — see
  [`skills/debug-zmk-split`](../skills/debug-zmk-split/SKILL.md)).
- Both XIAOs are also connected over USB-C, which carries CDC ACM (ZMK
  Studio RPC / console, when the firmware enables it) independently of the
  SWD connection.

## Where it runs

The actual build/flash/debug work happens inside an unprivileged **LXC/LXD
container** on a Linux host, not directly on the host. The host only owns the
physical USB devices and passes the relevant ones through to the container;
everything else (Nix, west, Zephyr SDK, SEGGER tools, this workspace) lives
inside the container.

Rough shape of the host-side setup (adapt vendor/product IDs and paths to
your own hardware):

1. **udev rules on the host** matching the relevant vendor/product IDs
   (SEGGER J-Link, and the ZMK application's own USB VID:PID once the board
   enumerates as a keyboard/composite device) grant the container's user
   group access and create stable `by-id`/`by-vendor` symlinks.
2. **Raw USB bus visibility**: the container gets the whole `/dev/bus/usb`
   character-device major allowed via cgroup device rules, plus (for LXD) a
   bind-mounted `disk` device for `/dev/bus/usb` itself, so newly-connected
   devices become visible without per-device container config changes.
3. **Per-interface device exposure** (the CDC ACM `tty`, `hidraw`, and
   `input`/evdev nodes for each probe/board) is the part that actually needs
   care once more than one identical-vendor/product device can be attached
   at once:
   - LXD's `unix-hotplug` device type only attaches *one* device per
     vendor:product match, even with multiple physical devices connected —
     it does not generalize to "attach every matching device".
   - The working approach instead is a small **reconciliation script**,
     triggered by a host udev rule on add/remove of a matching device, that
     enumerates every currently-connected `tty`/`hidraw`/`input` node for the
     relevant vendor/product classes, derives a name from each device's own
     USB **serial number** + interface number (something like
     `<class>-<tty|hidraw|input>-<serial>-<interface>`), and adds/updates/
     removes one LXD `unix-char` device per node to match reality. Because it
     keys off the device's own serial number rather than connection order or
     a fixed path, it's stable across replugging and scales to N identical
     devices.
   - This also sidesteps a related pitfall: fixed paths like
     `/dev/hidraw0`/`/dev/ttyACM0` or "first device of this vendor:product"
     symlinks are non-deterministic once two identical devices are attached
     — which one gets which number depends on USB enumeration order, which
     can change on every replug or container restart.
4. **BLE**: rather than passing a Bluetooth *controller* into the container
   (which doesn't work well for BLE central/peripheral roles inside an
   unprivileged container's network namespace), the container talks to the
   **host's own BlueZ** over D-Bus. The host's system D-Bus socket directory
   is bind-mounted into the container (outside `/run` itself, since
   container-internal `systemd` re-mounts `/run` at boot and would shadow a
   mount placed directly under it), and tools inside the container point
   `DBUS_SYSTEM_BUS_ADDRESS` at the bind-mounted socket to run `bluetoothctl`
   commands (e.g. to confirm a peripheral's BLE advertisement) against the
   host's real Bluetooth adapter.

None of this is specific to Claude/Codex — it's just what a from-scratch
reproduction on another LXC/LXD host would need to get both probes and both
boards reliably visible inside the container.

## Concurrent use

The rig is one physical resource shared by however many agent sessions are
running in this workspace. Anything that touches a probe or board must hold
the cooperative per-device locks described in
[hardware-locking.md](hardware-locking.md) (helper:
[`tools/hw-lock`](../tools/hw-lock)).

## Known rig-specific quirks

These are particular to the physical units in this rig (not general LXC/ZMK
knowledge), and are the kind of thing worth re-discovering quickly rather
than re-debugging from scratch:

- One of the two XIAO units has a flash layout quirk where a stock
  `xiao_ble` build linked at the normal application partition offset never
  boots (deterministic HardFault at reset). Debug builds for that unit need
  a devicetree overlay overriding the code partition to start at `0x0`
  instead. See
  [`skills/develop-zmk-module/references/hardware-rig.md`](../skills/develop-zmk-module/references/hardware-rig.md)
  for the exact overlay.
- A J-Link probe that has never been connected to from this host's SEGGER
  tools before may perform a one-time firmware update on first connect,
  during which it looks unreachable/re-enumerates under a different USB
  product ID. Give it a long timeout (a minute or more) instead of assuming
  the probe or its USB pass-through is broken.
- When reusing a full debug-probe development board (rather than a
  standalone probe) as one of the two J-Links, double check its SWD lines
  are actually routed to the *external* target and not left connected to its
  own onboard chip — `JLinkExe`'s core-identification warning
  (`Identified core does not match configuration`) catches this before you
  waste time on a failing flash attempt.

For the full agent-oriented workflows (build, flash, Studio RPC, GDB/RTT,
two-board split debugging), see the
[`skills/`](../skills) directory, in particular `build-zmk-config`,
`debug-zmk-jlink`, `develop-zmk-module`, and `debug-zmk-split`.
