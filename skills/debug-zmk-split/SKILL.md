---
name: debug-zmk-split
description: Debug a ZMK split keyboard on real hardware by driving two boards (central + peripheral) at once, each with its own SEGGER J-Link. Use when verifying split BLE pairing/behavior, debugging split-specific bugs (peripheral not connecting, split relay/RPC issues, role-specific freezes), or when a task needs two physical XIAO-class boards flashed and observed simultaneously rather than the single-board flow in $debug-zmk-jlink.
---

# Debug ZMK Split Keyboard With Two J-Links

## Operating Model

This skill extends `$debug-zmk-jlink` to two boards debugged concurrently. Use `$debug-zmk-jlink` first to make sure the single-probe basics (tool discovery, one board's Studio RPC, one GDB session) work; this skill only adds what changes when a *second* board and a *second* probe are in the loop:

1. Identify both J-Link probes and confirm each is actually reachable (not just listed) before assuming the rig is ready.
2. Build a central firmware and a peripheral firmware from the same `zmk-config`/test fixture (matching board/shield, split-role Kconfig differs).
3. Flash each board with its own probe, selected explicitly by serial — never rely on default/first-found probe selection with two attached.
4. Power/observe both boards together. Verify split pairing over BLE (host BlueZ scan, or each side's own logs/Studio RPC), not just that each board boots alone.
5. Only once pairing is confirmed, attach GDB/RTT to either or both sides to chase a specific bug.

## Lock the Whole Rig First

Split debugging uses both probes and both boards at once, so acquire **every** rig resource before any hardware command (including the `ShowEmuList` below) and hold them for the whole hardware session, per `docs/hardware-locking.md`:

```bash
SID=<your-session-id-or-worktree-name>   # same value on every call
"$ZMK_WORKSPACE"/tools/hw-lock acquire --owner "$SID" --task "split debug" \
  $("$ZMK_WORKSPACE"/tools/hw-lock list --names)
```

Heartbeat with `hw-lock touch --owner "$SID" ...` at the start of each batch of hardware commands (at least every 3 min — locks go stale at 10 min), and `hw-lock release --owner "$SID" --all` as soon as hardware work ends. If acquisition fails because another session holds part of the rig, wait with `--wait <sec>` or report the contention instead of proceeding.

## Required Setup

Two SEGGER J-Links, each SWD-wired to its own XIAO-class board, both attached to the same host/container. Confirm both probes and cross-check that each is *actually* reachable — `ShowEmuList` listing a probe is necessary but not sufficient:

```bash
printf 'ShowEmuList\nExit\n' > /tmp/jlink-show-emulators.jlink
JLinkExe -NoGui 1 -CommandFile /tmp/jlink-show-emulators.jlink   # note both serials

# Cross-check each J-Link's raw USB node actually exists (LXC/container environments)
for d in /sys/bus/usb/devices/*; do
  [ -f "$d/idVendor" ] && [ "$(cat "$d/idVendor")" = "1366" ] && \
    echo "$d: product=$(cat "$d/idProduct") busnum=$(cat "$d/busnum") devnum=$(cat "$d/devnum") serial=$(cat "$d/serial" 2>/dev/null)"
done
stat "/dev/bus/usb/$(printf '%03d' "$busnum")/$(printf '%03d' "$devnum")"   # per probe found above
```

If `stat` says "No such file" for a probe that `ShowEmuList` still shows, that probe's raw USB device node was never bind-mounted into the container — a host-side LXD pass-through gap, not a wiring or firmware problem. Confirm with a real connect attempt before trusting it:

```bash
printf 'SelectEmuBySN %s\nExit\n' "<serial>" > /tmp/jlink-probe-one.jlink
timeout 15s JLinkExe -NoGui 1 -CommandFile /tmp/jlink-probe-one.jlink
```

`Cannot connect to the probe/programmer` on *every* line (including plain `device`/`si`/`speed`, before any target-connect step) means the probe itself is unreachable — stop and get the container's USB pass-through fixed (host owner needs to add/repair an LXD `usb` device for that probe's vendor:product, mirroring whatever config already works for the first probe) before proceeding. Do not try to work around this with `mknod` inside the container — a manually created usbfs node does not behave like the real one and a connect attempt against it can hang for minutes; repeated failed attempts against an unreachable probe have also been observed to knock a *different, working* probe's USB descriptor into a recovery-looking product ID. If that happens, stop and ask for a probe power-cycle.

## Identify Which Probe Drives Which Board

SWD wiring is physically fixed per rig; you cannot redirect a probe to the other board in software. Confirm the pairing empirically rather than assuming:

```bash
printf 'SelectEmuBySN %s\ndevice nRF52840_xxAA\nsi SWD\nspeed 4000\nhalt\nr0\nExit\n' "<serial>" > /tmp/probe-which-board.jlink
JLinkExe -NoGui 1 -CommandFile /tmp/probe-which-board.jlink
```

A successful `halt` (not `Cannot connect`) confirms that probe is wired to *some* board; confirm *which* by flashing a build with a distinctive `CONFIG_ZMK_KEYBOARD_NAME` and checking which USB device / BLE advertisement name changes (`lsusb`, `bluetoothctl` — see below).

**Check the identified core type before flashing, not just that `halt` succeeded.** A probe that reports "J-Link OB-nRF5340-..." as its `ProductName` may be a full nRF5340-DK whose SWD lines are still wired to its *own onboard* nRF5340 chip rather than routed out to an external header connected to your XIAO. `halt`/reset can succeed against that onboard chip and look like a normal connection, but flashing an nRF52840 image against it fails partway (`Timeout while preparing target, RAMCode did not respond in time!`) because the actual silicon doesn't match. Confirm the core type explicitly before trusting the connection:

```bash
printf 'SelectEmuBySN %s\ndevice nRF52840_xxAA\nsi SWD\nspeed 4000\nr\nExit\n' "<serial>" > /tmp/probe-core-check.jlink
JLinkExe -NoGui 1 -CommandFile /tmp/probe-core-check.jlink
```

`WARNING: Identified core does not match configuration. (Found: Cortex-M33, Configured: Cortex-M4)` (or "Cortex-M33 identified" instead of "Cortex-M4 identified") means this probe is not actually talking to your nRF52840 XIAO — it's on a Cortex-M33 part (nRF5340/nRF9160-class), most likely the probe's own onboard target. This is a physical wiring/rig configuration issue (e.g. an nRF5340-DK's onboard/external target select jumper not set to external), not something fixable from the container or host LXD config — stop and get the physical SWD wiring checked rather than retrying flashes against it.

## Build Central + Peripheral Firmware

`zmk-feature-custom-settings/tests/zmk-config/build.yaml` already defines a matching pair built from the same board/shield (`xiao_ble//zmk` + `tester_xiao`) with only the split-role Kconfig/snippets differing — use it directly rather than authoring new test fixtures:

- `custom_settings_split_peripheral_with_rpc_relay`: snippet `custom-settings-split-rpc-relay` only (default role = peripheral). No Studio/console — this board won't expose a `zmk-hp-zmk-tty-*` node.
- `custom_settings_split_central_with_rpc_relay`: snippets `custom-settings-split-rpc-relay` + `custom-settings-split-central` + `studio-rpc-usb-uart`. Sets `CONFIG_ZMK_SPLIT_ROLE_CENTRAL=y` and enables Studio over USB CDC ACM, so this board *does* get a `zmk-hp-zmk-tty-*` node.

Build both with `$build-zmk-config`'s `west zmk-build`:

```bash
west zmk-build tests/zmk-config -d tests/zmk-config/build -q
```

You only need the two `*_split_*` artifacts for pairing; the other targets in that `build.yaml` are unrelated single-board configs.

This only verifies that the two boards pair and run as a split (BLE connection from peripheral to central) — it does not exercise `zmk-feature-custom-settings`'s own runtime-settings behavior. Treat the RPC-relay snippet purely as a stock split test fixture.

## Flash Each Board With Its Own Probe

Flash sequentially, each with its own `SelectEmuBySN`:

```bash
cat > /tmp/flash-peripheral.jlink << EOF
SelectEmuBySN <peripheral-probe-serial>
device nRF52840_xxAA
si SWD
speed 4000
r
loadfile <path>/custom_settings_split_peripheral_with_rpc_relay/zephyr/zmk.hex
r
go
Exit
EOF
JLinkExe -NoGui 1 -CommandFile /tmp/flash-peripheral.jlink

cat > /tmp/flash-central.jlink << EOF
SelectEmuBySN <central-probe-serial>
device nRF52840_xxAA
si SWD
speed 4000
r
loadfile <path>/custom_settings_split_central_with_rpc_relay/zephyr/zmk.hex
r
go
Exit
EOF
JLinkExe -NoGui 1 -CommandFile /tmp/flash-central.jlink
```

Never `erase` (removes the UF2 bootloader region). If a board HardFaults at reset with `PC = 0` after flashing (no USB enumeration), that unit's flash partition table needs the `CONFIG_FLASH_LOAD_OFFSET` workaround from `$develop-zmk-module`'s `references/hardware-rig.md` — a plain `-DCONFIG_FLASH_LOAD_OFFSET=0x0` cmake arg does **not** fix it on this board family; you need the devicetree `code_partition` override documented there, passed via `-DEXTRA_DTC_OVERLAY_FILE`.

## Verify Pairing (the actual "does split work" check)

Don't stop at "both boards flashed" — confirm they actually paired:

1. **Peripheral advertises.** Even before a central is present, a correctly-booted peripheral advertises over BLE. If host BlueZ is reachable from the container (see `$develop-zmk-jlink`'s LXC runbook: `DBUS_SYSTEM_BUS_ADDRESS=unix:path=/mnt/host-dbus/system_bus_socket`), confirm with a scan:

   ```bash
   export DBUS_SYSTEM_BUS_ADDRESS=unix:path=/mnt/host-dbus/system_bus_socket
   timeout 8s bluetoothctl --timeout 8 scan on | grep -i "<CONFIG_ZMK_KEYBOARD_NAME>"
   ```

   Seeing the board's keyboard name appear as a discovered device confirms the peripheral firmware booted and is advertising — useful as an early signal even with only one board reachable. **This does not confirm the two boards paired with each other** — the host's own Bluetooth adapter is a third, unrelated radio, so a scan can only see that the peripheral advertises, not that the central connected to it.

2. **RTT logs from both sides — the real proof.** BLE traffic between the two boards' own radios is invisible to the host adapter, so the only way to confirm actual pairing is logs from the boards themselves. Rebuild both artifacts with a log backend added (`-DCONFIG_LOG=y -DCONFIG_LOG_BACKEND_RTT=y -DCONFIG_USE_SEGGER_RTT=y -DCONFIG_SEGGER_RTT_BUFFER_SIZE_UP=8192 -DCONFIG_LOG_PROCESS_THREAD_STARTUP_DELAY_MS=0`; ZMK's own `CONFIG_ZMK_LOG_LEVEL` already defaults to debug), flash both, then read RTT per `$develop-zmk-module`'s `references/hardware-rig.md` recipe (zero the `_SEGGER_RTT` signature before each reset, `mem32`+`savebin`+`strings` on the up-buffer-0 descriptor). Confirmed 2026-07-05 on real hardware — the central's log shows the full GATT discovery + subscribe sequence, and both sides log a security/bonding event carrying the *other* board's BLE address:

   ```
   # central log
   split_central_service_discovery_func: Found split service
   split_central_chrc_discovery_func: Found position state characteristic
   split_central_chrc_discovery_func: Found relay event characteristic
   split_central_subscribe: [SUBSCRIBED]
   split_central_chrc_discovery_func: Found select physical layout handle
   security_changed: Security changed: <peripheral's BLE identity address> (random) level 2

   # peripheral log
   security_changed: Security changed: <central's BLE address> (random) level 2
   split_svc_pos_state_ccc: value 1
   split_svc_relay_event_ccc: value 1
   split_svc_select_phys_layout_callback: Selecting physical layout after GATT write of 0
   ```

   Cross-checking that each side's `security_changed` address matches the *other* side's own advertised/identity address (visible in that board's own boot log, `bt_hci_core: Identity: <addr>`) is what actually proves these two specific boards bonded with each other, not just that each is doing *something* over BLE independently.

3. **Central reports a connected peripheral over Studio RPC**, as a lighter-weight recurring check once you've confirmed pairing once via RTT (the central has the `zmk-hp-zmk-tty-*` node; the peripheral does not, since it has no `studio-rpc-usb-uart` snippet):

   ```bash
   PYTHONPATH=tools tools/zmk-studio-rpc --workspace <west-topdir> --port /dev/zmk-hp-zmk-tty-<central-serial>-00 info
   ```

4. **Both sides halted at once, if you need to correlate state.** Run two GDB servers concurrently, one per probe, on distinct ports:

   ```bash
   JLinkGDBServerCLExe -USB <peripheral-serial> -device nRF52840_xxAA -if SWD -speed 4000 -port 2331 -swoport 2332 -telnetport 2333
   JLinkGDBServerCLExe -USB <central-serial>    -device nRF52840_xxAA -if SWD -speed 4000 -port 2341 -swoport 2342 -telnetport 2343
   ```

   Then two `gdb` instances, one per `target remote :2331` / `:2341`. Halting both at once (rather than one at a time) is the only way to catch a race between the two roles.

## GDB Attach Itself Can Destabilize BLE Radio Timing — Don't Attribute Crashes To Firmware Without A Hands-Off Control

Confirmed 2026-07-07 on real hardware (zmk-feature-watchdog split-relay investigation): a sustained `JLinkGDBServerCLExe` + `gdb ... continue` session attached to a connected split peripheral reproduced a `z_fatal_error`/`LL_ASSERT_OVERHEAD`-class crash (BLE controller radio-event-prepare timing assertion, in `prepare_cb()` of `lll_peripheral.c`/`lll_central.c`/`lll_adv.c`) at **~60-100% of attempts across 40+ trials**, often within 1-20s of attach — even with the module/feature under test fully disabled (`CONFIG_ZMK_WATCHDOG=n`, `CONFIG_ZMK_SPLIT_RELAY_EVENT=n`, i.e. a stock split peripheral with none of the code being investigated). Repeating the *exact same firmware* with **zero JLink contact after the initial flash** (central-side USB devnum + actual RPC results as the only observability) survived 90s+ idle windows with no crash at all, and only showed ~50% instability specifically when a real RPC round-trip was attempted — a very different picture. A third condition — brief `halt` → `savebin`/`regs` → immediate `go` (a few hundred ms of contact, no held breakpoint, no sustained attach) for grabbing a log snapshot or a one-shot PC/register check — behaved like the hands-off case (0/5 crashes across repeated relay attempts in one run), not like the sustained-GDB case.

**Practical implication:** `JLinkGDBServerCLExe`'s connect-time halt plus a live `continue` session appears to hold the target halted/contended in a way that measurably increases the odds of tripping this radio-timing assertion, independent of whatever bug is actually being chased. Before concluding "the firmware crashes" from a GDB session on BLE/radio-timing-sensitive code:

1. Reproduce with a **hands-off control** first — flash, then do not touch that board with JLink again; observe only through the other board's USB/RPC behavior (or a separate non-JLink channel) over a comparable or longer window (60-90s+, repeated 2-3x).
2. If a crash only shows up once GDB is attached and holding the core, treat GDB-attach-induced radio-timing pressure as a live confound, not settled proof of a firmware bug — say so explicitly rather than reporting the GDB-observed rate as if it were the natural crash rate.
3. If you need *some* visibility without the sustained-attach risk, prefer brief `halt`+`savebin`/`regs`+`go` snapshots (in, read, out — no held breakpoint) over a live `continue`-based GDB session; this matched the hands-off crash rate far better in the confirmed case above.
4. When a breakpoint catch is genuinely necessary (e.g. to read an ESF/backtrace once), still run a hands-off control afterward before trusting the observed frequency, and disclose that the debugger itself may have inflated it.

## Before Chasing Timing/Connection Theories, Check For Leftover Diagnostic Scaffolding

Confirmed 2026-07-07 (same investigation as above): after exhausting an entire session's worth of hardware-timing hypotheses (BLE controller radio-timing assertions, ATT buffer pool exhaustion, a peripheral BLE-init hang under RTT logging overhead) for a "central sends a relay request, peripheral never responds" symptom, the actual cause was much simpler and entirely invisible to hardware tracing: the peripheral-side handler still had diagnostic scaffolding from an *earlier* debugging session — a `printk()` immediately followed by an unconditional `return` placed before the handler's real logic ever ran. The peripheral was silently no-op'ing on every single request; no amount of GDB backtraces, RTT log tracing, or non-halting SWD polling of the *transport* layer would reveal this, because the bug wasn't in the transport — it was that the receiving code never even tried to do its job. It was found by reading the suspect source file directly, not by any hardware technique.

**Practical implication:** before spending hardware-debugging time on timing/connection/transport hypotheses for a "response never arrives" or "request never processed" symptom, `grep` the suspect handler(s) for leftover `printk`/`LOG_*` diagnostic lines and early `return`/`break` statements — especially ones with comments like "DIAG STEP", "bisecting", "revert before committing", or similar session-scoped debugging markers. Confirm the handler's real logic actually executes (even a single log line or counter increment placed *at the very top* of the function, distinct from any pre-existing early-return diagnostic, is enough) before assuming the bug is in the transport/timing layer underneath it. This is especially easy to miss when a long investigation spans many compaction/summary boundaries — a "fully reverted" claim in an earlier summary is not a substitute for re-`grep`ping the file.

## Report Shape

Return:

- Which probe serial is wired to which board (peripheral/central), established empirically.
- Build identity for both artifacts (board/shield/snippets, artifact paths).
- Whether each board booted (USB enumeration / BLE advertisement observed) after flashing, including whether the flash-load-offset workaround was needed.
- Pairing evidence: BLE scan result, central-side Studio RPC / log evidence of a connected peripheral — not just "both flashed".
- Any environment gaps hit (unreachable probe, missing device node) and what host-side fix they need, separate from firmware/wiring findings.
- Next experiment, scoped to the observed split-specific behavior.
