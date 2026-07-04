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
  ("Abyss Tester XIAO" era): a stock `xiao_ble` build linked at 0x27000 will
  never run (deterministic HardFault loop at reset, identical across builds =
  boot-chain problem, not app bug). Workaround for validation: rebuild with
  `CONFIG_FLASH_LOAD_OFFSET=0x0` via an extra overlay so the app's vector
  table sits at 0x0, then SWD-flash that hex. Symptom of the problem: no USB
  enumeration after flashing; J-Link halt shows PC in a `b.n` self-loop.
- No `/dev/ttyACM*` in this sandbox. Use the pyusb transport:
  `PYTHONPATH=tools tools/zmk-studio-rpc --workspace <west-topdir> --transport
  pyusb --usb-data-interface <N> ...` (run from zmk-workspace root). Without
  `--usb-data-interface` it lists candidate interfaces; probe each with `info`.
- CLI RPC round-trip is dominated by Python startup (~150–200 ms/call); raw
  transport latency is < 50 ms.
