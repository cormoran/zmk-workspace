# This PC's ZMK hardware rig

- Seeed XIAO nRF52840 + PMW3610 trackball sensor, wired: SPI0 SCK=P0.05 (D5),
  MOSI=MISO=P1.13 (D8, 3-wire shared), CS=`&xiao_d 10`, IRQ=`&xiao_d 9`
  (active-low, pull-up). Same wiring as
  zmk-keyboard-dya2 `snippets/right-trackball/right-trackball.overlay`.
  3-wire wiring ⇒ set `disable-burst-read` on the sensor node.
- SEGGER J-Link attached; `JLinkExe -device nRF52840_xxAA -if SWD -speed 4000
  -autoconnect 1 -CommandFile <file>`. JLinkExe cannot read command files from
  /dev/stdin — write a real temp file.
- Flash over SWD with `loadfile <build>/zephyr/zmk.hex` + `r` + `go`.
  NEVER `erase` (would remove the UF2 bootloader region).
- **This unit's flash below 0x27000 contains stale non-bootloader firmware**
  ("Abyss Tester XIAO" era): a stock `xiao_ble` build linked at the default
  `code_partition` offset (0x27000, from
  `nrf52840_partition_uf2_sdv7.dtsi`) will never run (deterministic HardFault
  loop at reset — `PC = 0`, `IPSR = 3 (HardFault)` on halt — identical across
  builds = boot-chain problem, not app bug). Symptom: no USB enumeration
  after flashing; J-Link halt shows `PC = 0`.
  **`-DCONFIG_FLASH_LOAD_OFFSET=0x0` alone does NOT fix this** (confirmed
  2026-07-05: the resulting `.uf2`/`.hex` still links at 0x27000 — this board
  family locates the load address from the devicetree `zephyr,code-partition`
  chosen node, not from `CONFIG_FLASH_LOAD_OFFSET`). The real workaround is a
  devicetree overlay that deletes the stock `reserved_partition_0`
  (SoftDevice placeholder, 0x0–0x27000) and `code_partition` nodes and
  redefines `code_partition` to start at 0x0 with enough room for the image
  (leave `storage_partition`/`boot_partition` untouched):
  ```
  /delete-node/ &reserved_partition_0;
  /delete-node/ &code_partition;

  &flash0 {
  	partitions {
  		compatible = "fixed-partitions";
  		#address-cells = <1>;
  		#size-cells = <1>;

  		code_partition: partition@0 {
  			label = "Application";
  			reg = <0x00000000 0x000ec000>;
  		};
  	};
  };

  / {
  	chosen {
  		zephyr,code-partition = &code_partition;
  	};
  };
  ```
  Pass it with `-DEXTRA_DTC_OVERLAY_FILE=<path-to-overlay>` (verify with
  `arm-zephyr-eabi-objdump -f zephyr/zmk.elf | grep 'start address'` → should
  read `0x0...`, and the west build log's `Converted to uf2` line → `start
  address: 0x0`). Then SWD-flash that hex per above. This board's flash
  partition table is otherwise unmodified — only apply this overlay for this
  specific unit's debug builds, not for firmware meant to boot from the UF2
  bootloader normally.
- As of 2026-07-05 this sandbox (LXC `zmk-dev`) has **two** SEGGER J-Links
  and up to **two** ZMK-app XIAOs attached at once; host-side udev/LXD
  reconciliation exposes each as serial-numbered device nodes named
  `/dev/zmk-hp-<jlink|zmk>-<tty|hidraw|input>-<serial>-<interface>` (no more
  fixed `/dev/ttyACM*`/`/dev/hidraw0`/`/dev/ttyACM-zmk-module-test` paths —
  those were removed). Find the current node with
  `ls /dev/zmk-hp-zmk-tty-*` (or `-hidraw-`/`-input-`) and pass it directly
  to `--port`:
  `PYTHONPATH=tools tools/zmk-studio-rpc --workspace <west-topdir> --port
  /dev/zmk-hp-zmk-tty-<serial>-00 info` — confirmed working end-to-end
  2026-07-05. The pyusb transport (`--transport pyusb
  --usb-data-interface <N>`) is still the fallback for a board whose current
  firmware has no CDC ACM console at all (e.g. `CONFIG_CONSOLE=n` with no
  `studio-rpc-usb-uart` snippet) — such boards have no `zmk-hp-zmk-tty-*`
  node, only `-hidraw-`/`-input-`.
- With two J-Links present, select the one wired to the target unit
  explicitly — don't rely on default/first-found selection:
  `JLinkExe -NoGui 1 -CommandFile <file>` where the command file starts with
  `SelectEmuBySN <serial>` (serials from `ShowEmuList`), or pass
  `-USB <serial>` on the JLinkExe command line. **Known gap (2026-07-05):**
  the second J-Link's raw `/dev/bus/usb/BBB/DDD` node was not present in
  this container even though `ShowEmuList`/`lsusb` saw it — `SelectEmuBySN`
  failed with `Cannot connect to the probe/programmer` for every command,
  not just target-connect ones. This needs a host-side LXD device fix
  (see `develop-zmk-module`'s note in the infra repo / ask the host owner to
  add a `usb` type device for that J-Link's vendor:product, mirroring the
  one that already works for J-Link #1). Repeated failed `SelectEmuBySN`
  attempts against an unreachable probe risk knocking the *other* probe's
  USB descriptor into a recovery-looking state (`1366:0101 "J-Link PLUS"`
  instead of its normal product ID) — stop retrying and ask for a probe
  power-cycle if you see that.
- CLI RPC round-trip is dominated by Python startup (~150–200 ms/call); raw
  transport latency is < 50 ms.
- The board's SWD pins (J-Link, wired to this sandbox) and its USB-C data
  port are electrically independent — USB-C can be plugged into any real
  host OS (a real Mac, a real Windows PC, etc.) while SWD debugging/logging
  from this sandbox keeps working unaffected. Useful for capturing real
  per-OS USB/BLE behavior: flash a debug build, have the human plug USB-C
  into the target host, then read logs over SWD as below.
- `JLinkRTTLogger`/`JLinkRTTClient` fail to find the RTT control block on
  this rig even when given the exact right address (from
  `arm-zephyr-eabi-nm zmk.elf | grep _SEGGER_RTT`) — always "RTT Control
  Block not found". Read RTT directly with `JLinkExe` instead:
  `mem32 <addr>, 0x8` to read the up-buffer-0 descriptor
  (sName/pBuffer/SizeOfBuffer/WrOff/RdOff), then
  `savebin <file> <pBuffer> <SizeOfBuffer>` + `strings` on the result.
- nRF52's `AIRCR.SYSRESETREQ` (what `JLinkExe`'s `r` does) does **not**
  clear RAM. After reflashing a *different* build, the old RTT control
  block's "SEGGER RTT" signature is still there, and SEGGER's RTT init
  skips re-initializing `WrOff`/`RdOff`/`pBuffer`/`sName` when it finds a
  valid-looking signature already present — symptom: `WrOff`/`RdOff` frozen
  forever even though the new firmware is running fine and logging
  elsewhere. Fix: before each `r`+`g`, zero the first 16 bytes at the
  `_SEGGER_RTT` address (`w4 <addr>, 0x00000000` x4) to blank the
  signature, forcing a real re-init on the next boot.
- `CONFIG_LOG_PROCESS_THREAD_STARTUP_DELAY_MS` defaults to 5000 in a normal
  ZMK build — no log backend flushes anything before then. Pass
  `-DCONFIG_LOG_PROCESS_THREAD_STARTUP_DELAY_MS=0` for hardware debug
  builds. Also size `CONFIG_SEGGER_RTT_BUFFER_SIZE_UP` generously (e.g.
  8192) — `DBG`-level ZMK boot logging is chatty and the default 1KB buffer
  overflows/wraps in well under a second.
