# Renode + ZMK/XIAO nRF52840 gotchas

Concrete, hard-won details from getting ZMK Studio RPC + split working under
Renode. Read this before touching the overlays/scripts — most of the
non-obvious behavior here cost real debugging time to pin down.

## Renode CLI / monitor

- Headless: `renode --disable-xwt -P <port> -e "<commands>"`. `-P` opens a
  raw TCP monitor on that port instead of a GUI; `--hide-log` suppresses
  Renode's own internal log (peripheral warnings etc.) — useful once you
  trust the setup, but turn it off (drop the flag) when debugging, since
  those "unimplemented register" warnings are often the whole story (see
  QSPI/USBD below).
- `.resc` `:description:` **must be a single line**. A multi-line
  `:description: >` YAML-style block breaks the monitor's tokenizer with
  `Could not tokenize here:` — and the failure is silent enough that the
  rest of script inclusion just doesn't happen (no sockets get created, no
  error surfaces to a client connecting to the monitor). Use `#` comments
  for anything longer than one line.
- `@relative/paths` inside `-e` strings and inside `.resc` files resolve
  against Renode's **current working directory**, not the script's own
  directory. `i @single.resc` when the process's cwd is
  `skills/test-zmk-renode/` and the file is actually at
  `platforms/single.resc` fails to find the file — same silent-failure mode
  as the description bug above (monitor comes up fine, but none of the
  script's `mach create`/`connector Connect`/`LoadELF` commands ever ran, so
  every UART socket you try to connect to just refuses the connection,
  forever). Always pass the path relative to the process's cwd (we launch
  Renode with `cwd=<skill dir>` and pass `platforms/<name>.resc`).
- `emulation CreateServerSocketTerminal <port> "<name>" false` — the
  trailing `false` disables Telnet IAC negotiation bytes, so the socket is a
  clean raw byte stream (matches `zmk,studio-rpc-uart`'s own framing, no
  telnet escaping to strip).
- **A `CreateServerSocketTerminal` port reliably serves exactly one client
  connection for the life of the Renode process.** Reconnecting a second
  client to the same port either gets nothing (RX direction, and no data
  the peripheral sends afterward gets forwarded either) — silently, no
  error on either end. This is not a "history buffer" that replays on
  reconnect. **Connect once, keep the socket open for the whole test.** A
  test harness that does "connect → read → disconnect → reconnect → read
  again" against the same port will see the second connection hang/starve
  even though the emulation is running fine. (`scripts/renode_test.py`'s
  `RenodeSession` is built around this constraint.)
- `sysbus.<uart> WriteChar <byte>` from the monitor injects a byte into
  that UART's RX line directly (bypassing any socket) — useful for
  isolating "is this a socket problem or a firmware problem" (see the RPC
  TX-storm bug below, which we diagnosed this way).
- `sysbus.<gpio> OnGPIO <pin> <true|false>` injects a GPIO level change —
  this is how we simulated a keypress for the T2 split test without real
  hardware (`kscan-direct` pins are plain GPIO inputs; toggling one from
  the monitor after boot looks like a switch closing/opening to the
  firmware).
- `emulation CreateUARTHub "<name>"` + `connector Connect sysbus.uartN
  <name>` on two different machines does form a real bidirectional
  point-to-point link (confirmed for T2 — see below). It is NOT the same
  mechanism as `CreateServerSocketTerminal`; a hub has no "first
  connection only" restriction since there's no TCP client involved at all.

## Platform description

- Renode's bundled `platforms/cpus/nrf52840.repl` is a generic, board-agnostic
  nRF52840 description (CPU, NVIC, uart0/uart1, radio, flash, ram, GPIO,
  timers, RNG, etc.) — exactly what a XIAO nRF52840 needs, since the XIAO
  adds no on-die peripherals beyond bare silicon. We keep a checked-in copy
  at `platforms/xiao_nrf52840.repl` (from Renode 1.16.1) so the test rig
  doesn't depend on the install layout of whatever Renode happens to be on
  `$PATH`.
- `uart0` is at `0x40002000`, `uart1` at `0x40028000` in both Renode's repl
  and Zephyr's nRF52840 devicetree — they line up 1:1, no relabeling needed
  between overlays and platform files.
- Flash region is `0x100000` (1MB), RAM `0x40000` (256KB) — matches the
  nRF52840's real specs, so `Memory region ... %age Used` from `west build`
  output is meaningful.

## Build: environment / west invocation

- `west build` needs `-s dependencies/zmk/app` (the actual Zephyr
  *application* source dir). Running `west build` from
  `zmk-feature-studio-rpc-perf/`'s own root without `-s` picks up that
  repo's own top-level `CMakeLists.txt`, which is a Zephyr *module*
  manifest (calls `zephyr_include_directories(...)` etc.), not an
  application — `west build` fails immediately with `Unknown CMake command
  "zephyr_include_directories"`.
- Needs `-DZMK_CONFIG=<...>/tests/zmk-config/config` (keymap/shield config)
  and `-DZMK_EXTRA_MODULES="<...>/tests/zmk-config;<studio-rpc-perf root>"`
  (the shield definition lives under `tests/zmk-config/boards/shields/`,
  and the custom RPC-perf handler C code/protos live in the repo root,
  which is itself a Zephyr module via `zephyr/module.yml`). Omitting either
  fails to find the `my_awesome_keyboard` shield or the custom Kconfig
  options.
- `ZEPHYR_TOOLCHAIN_VARIANT=zephyr` and `ZEPHYR_SDK_INSTALL_DIR=<...>` need
  to be set explicitly in this environment — the CMake user package
  registry (`~/.cmake/packages/Zephyr/*`) can point at a Zephyr checkout
  from a *different* project (leftover from other agent sessions sharing
  the same home directory), which derails `find_package(Zephyr)` in
  confusing ways (errors mentioning an unrelated project's path). A Zephyr
  SDK 0.16.8 install was found under `~/agent-home/zephyr-sdk-0.16.8`;
  `scripts/build_fw.py`'s `find_zephyr_sdk()` searches a few common
  locations rather than hardcoding this.

## Boot hangs (silent — no crash, no log, no banner, ever)

Renode's nRF52840 platform models some peripherals only as generic
SVD-register stubs (reads return whatever the `.svd` says, writes are
logged as a `WARNING` and dropped) rather than functionally. Two of these
are enabled by default on the stock `xiao_ble` board devicetree and both
cause a **permanent busy-wait in Zephyr driver init that runs before
`main()`** — the firmware truly never boots, with zero observable output on
any UART, and nothing in Renode's log at default verbosity (you have to
drop `--hide-log` and watch for `ReadDoubleWord from an unimplemented
register ... (10000)` repeating forever to catch it).

1. **QSPI external NOR flash (`&qspi` / `p25q16h`).** The board dts enables
   this by default. Zephyr's `nordic_qspi_nor` driver init busy-waits on
   `EVENTS_READY`, which Renode's stub never sets. Disabling the parent
   `&qspi` node is not enough — devicetree `status = "disabled"` does not
   cascade to children, and Kconfig still sees
   `DT_HAS_NORDIC_QSPI_NOR_ENABLED=y` from the child `p25q16h` node alone,
   so the driver still gets built and still hangs. **Must disable both
   `&qspi` and `&p25q16h` explicitly** (see `overlays/*.overlay`). This
   flash chip is not ZMK's settings backend (that's the internal
   `flash_controller` via `zephyr,flash = &flash0`), so disabling it is
   safe for emulation.
2. **USB (`&usbd` / CDC-ACM / HID).** `xiao_ble_common.dtsi` unconditionally
   includes `<boards/common/usb/cdc_acm_serial.dtsi>`, which enables a
   `board_cdc_acm_uart` node under `&usbd`. Even with `CONFIG_ZMK_USB=n`
   (so ZMK's own `usb.c` never runs), the *board*-level Kconfig cascade
   (`boards/seeed/xiao_ble/Kconfig.defconfig` → `Kconfig.cdc_acm_serial.defconfig`,
   gated by `BOARD_SERIAL_BACKEND_CDC_ACM`, default y whenever
   `BOARD_REQUIRES_SERIAL_BACKEND_CDC_ACM` is set, which this board sets
   unconditionally) still force-enables `CONFIG_USB_DEVICE_STACK` and
   `CONFIG_USB_DEVICE_INITIALIZE_AT_BOOT`, so *something* still calls
   `usb_enable()` at boot regardless. That reaches
   `dependencies/zephyr/drivers/usb/common/nrf_usbd_common/nrf_usbd_common.c`'s
   `usbd_enable()`:
   ```c
   NRF_USBD->ENABLE = 1;
   while ((NRF_USBD->EVENTCAUSE & USBD_EVENTCAUSE_READY_Msk) == 0) { }
   ```
   `EVENTCAUSE.READY` is set by real silicon automatically ~microseconds
   after `ENABLE`, as part of the analog USB PHY power-up — **it has
   nothing to do with a host being attached** — but Renode's USBD is a pure
   SVD-register stub and never sets it. This is a genuinely unconditional
   hang: we confirmed a *pure ZMK-HID-only* build (no CDC-ACM node at all,
   `CONFIG_ZMK_USB=y`, otherwise minimal) hits the exact same loop, so
   there is no way to get any USB path working under this Renode
   nRF52840 model. Fix: `-DCONFIG_ZMK_USB=n
   -DCONFIG_BOARD_SERIAL_BACKEND_CDC_ACM=n` plus disabling `&board_cdc_acm_uart`
   and `&usbd` in the devicetree overlay (belt-and-suspenders; the Kconfig
   fix alone is what actually matters, since with `USB_DEVICE_STACK` off
   `usb_device.c` isn't even compiled).
3. **Console/logging are not on by default without USB.** Once USB (and its
   Kconfig cascade) is off, `CONFIG_CONSOLE`, `CONFIG_UART_CONSOLE`, and
   `CONFIG_LOG` are all simply unset (nothing else on this board turns them
   on) — `printk`/log output goes nowhere, even though the firmware *is*
   booting fine. Needs `-DCONFIG_LOG=y -DCONFIG_CONSOLE=y
   -DCONFIG_UART_CONSOLE=y -DCONFIG_UART_INTERRUPT_DRIVEN=y` explicitly
   (this mirrors what ZMK's own `ZMK_USB_LOGGING`/`ZMK_RTT_LOGGING` Kconfig
   options `select`, just retargeted at a plain UART instead of USB/RTT).

## ZMK's Studio RPC transport is gated behind USB HID readiness

This is the subtlest one and the reason T1 needed more than "bind
`zmk,studio-rpc-uart` to a UART and build":

- ZMK's UART-based Studio RPC transport
  (`dependencies/zmk/app/src/studio/uart_rpc_transport.c`) registers itself
  via `ZMK_RPC_TRANSPORT(uart, ZMK_TRANSPORT_USB, start_rx, stop_rx, ...)`
  — tagged `ZMK_TRANSPORT_USB`, **regardless of physical carrier**. On real
  hardware this only ever gets used together with the `studio-rpc-usb-uart`
  snippet's actual USB CDC-ACM, so the tag was presumably never meant to
  matter, but the transport-selection code doesn't know or care which UART
  it's driving.
- `zmk_rpc`'s `refresh_selected_transport()`
  (`dependencies/zmk/app/src/studio/rpc.c`) only calls a transport's
  `rx_start()` once `zmk_endpoint_get_selected().transport` matches that
  transport's tag. For `ZMK_TRANSPORT_USB` this requires
  `is_usb_ready()` → `zmk_usb_is_hid_ready()` → a real, host-negotiated
  `USB_DC_CONFIGURED` state (`dependencies/zmk/app/src/endpoints.c`,
  `dependencies/zmk/app/src/usb.c`).
- Since USB is fundamentally non-functional under this Renode nRF52840
  model (see above — `usb_enable()` itself never returns), that
  `USB_DC_CONFIGURED` state can never happen. So the real UART transport's
  `rx_start()` (which enables the RX IRQ) is **never called** — the UART
  itself, the ISR, the framing code all work fine, but nothing ever arms
  RX, so the emulated board is deaf on the wire. This produces zero
  symptoms: no log line, no error, no crash — a request sent over the
  socket (or injected via `sysbus.uart1 WriteChar`) just vanishes.
- Fix (no vendored ZMK files touched): `renode-test-module/` adds a second,
  functionally-identical UART transport
  (`src/renode_uart_transport.c`, essentially a copy of ZMK's own file)
  tagged `ZMK_TRANSPORT_NONE` instead of `ZMK_TRANSPORT_USB`.
  `ZMK_TRANSPORT_NONE` is exactly what `zmk_endpoint_get_selected()`
  reports when no output-endpoint preference has been set — the natural
  state of a fresh board with `CONFIG_ZMK_USB=n`/`CONFIG_ZMK_BLE=n` and an
  empty settings partition, no faking required. Gated behind
  `CONFIG_ZMK_RENODE_STUDIO_UART_TRANSPORT` (default n); real hardware
  builds must never enable it. `CONFIG_ZMK_STUDIO_TRANSPORT_UART=n` is
  passed alongside it to keep the real (unusable-here) transport from also
  attaching its own IRQ callback to the same UART device.

## RPC TX-IRQ storm: only the first request/response round-trip ever worked

Once the above got a *single* Studio RPC request/response round-tripping
correctly (a real `GetDeviceInfoResponse{name: "MAK"}` decoded from the
wire — genuine proof the whole stack works), a **second** request over the
same still-open connection (or a fresh connection, or a byte-for-byte
`sysbus.uart1 WriteChar`-injected request bypassing sockets entirely) would
silently time out forever — no error, no log, nothing.

Root cause: both ZMK's own `uart_rpc_transport.c` and our copy leave this
commented out in the TX interrupt handler:

```c
// if (ring_buf_size_get(tx_buf) == 0) {
//     uart_irq_tx_disable(dev);
// }
```

So once a response finishes sending, the TX IRQ is left permanently
enabled. Under Renode, `uart_irq_tx_ready()` reads as a level condition
that stays true with nothing queued to send — the CPU gets re-interrupted
immediately after returning from the ISR, forever, and the
`studio_rpc_thread` (a normal-priority kernel thread that does the actual
decode/dispatch) never gets scheduled again. Confirmed via
`sysbus.cpu ExecutedInstructions` growing steadily (millions of
instructions/sec) even while completely "stuck" — this is a busy interrupt
storm, not a halt.

Fix (in our own `renode_uart_transport.c` only — this is *not* a change to
vendored ZMK code): explicitly `uart_irq_tx_disable(uart_dev)` once the TX
ring buffer drains. `tx_notify()` already re-enables it whenever there's
something new to send. This is a one-line, clearly-commented deviation from
upstream; whether real UART hardware's TX-ready semantics differ enough
that upstream never noticed is unclear, but the fix is unambiguously
correct behavior either way.

## Wired split (T2): works, but watch the boot-time race

`emulation CreateUARTHub` + `connector Connect sysbus.uart1 <hub>` on both
machines' `uart1` does form a working bidirectional link — confirmed with a
`sysbus.gpio0 OnGPIO 2 true/false` injected on the peripheral several
seconds after boot, which the central received and applied as a real
`position: 0` key event.

The catch: this shield's `kscan-direct` fires a couple of synthetic
key-press/release events in the first few milliseconds of virtual boot time
(looks like uninitialized/floating GPIO input state resolving once pinctrl
applies — harmless, and not something we rely on for testing). If you
watch for those specific events on the central side, you'll likely miss
them: they can fire before the central's own
`uart_irq_rx_enable()` (called from `zmk_split_wired_central_init`'s
`SYS_INIT`) has necessarily run, since both machines start executing from
t=0 simultaneously and there's no cross-machine ordering guarantee. Central
received *zero* of these two boot-time events in testing, but reliably
received a GPIO toggle injected ~3 real seconds after `start` (by which
point both sides are long done with `SYS_INIT`). **Wait a couple of
seconds after boot before generating/relying on a "real" cross-machine
event in a test.**

## BLE (T3): breaks before any peer is even involved

`CONFIG_ZMK_BLE=y` on a single, isolated board (no split, no Renode BLE
medium wiring, no peer at all) reliably crashes ~10 seconds after boot:

```
[00:00:00.000,030] <err> bt_settings: settings_subsys_init failed (err -33)
[00:00:00.000,091] <err> zmk: BLUETOOTH FAILED (-33)
...
ASSERTION FAIL [err == 0] @ .../subsys/bluetooth/host/hci_core.c:436
	Controller unresponsive, command opcode 0x1009 timeout with err -11
>>> ZEPHYR FATAL ERROR 3: Kernel oops on CPU 0
>>> Halting system
```

Renode's nRF52840 radio peripheral itself is not obviously broken — Renode
ships its own bundled multi-node Zephyr BLE examples
(`scripts/multi-node/nrf52840-ble-zephyr.resc`, using
`emulation CreateBLEMedium`) that presumably work — so this looks like an
interaction between ZMK's Bluetooth settings/identity bring-up and
something Renode's controller model doesn't handle, rather than "BLE is
unusable in Renode" in general. We did not chase this further (capped per
the mission's T3 time-box); `scripts/renode_test.py`'s
`test_t3_ble_single_board_boot` reproduces and asserts this exact failure
signature so a future session has a concrete, automated starting point
rather than having to rediscover it. `RENODE_ZMK_RUN_T3=1
python renode_test.py -v RenodeZmkTests.test_t3_ble_single_board_boot` to
reproduce; it's skipped by default since it documents a known failure, not
a passing capability.

## Command-line gotcha: `-D` flags are last-wins

Kconfig options passed via `west build -- -DCONFIG_X=...` behave like a
plain assignment list processed in order — the *last* occurrence of a given
symbol on the command line wins. This bit us once: appending
`build_fw.COMMON_ARGS` (which sets `CONFIG_ZMK_BLE=n` for the other tiers)
*after* an explicit `-DCONFIG_ZMK_BLE=y` silently put BLE back to `n`. Not
specific to Renode, but easy to trip over when composing arg lists from a
shared "common" list plus per-test overrides.
