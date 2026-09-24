# XIAO nRF52840 preflight and recovery

Use this before a J-Link flash or a conclusion that the ZMK application is broken. This is for the original Seeed XIAO nRF52840 and Sense, **not** the Plus variants. The exact board variant matters when selecting a bootloader image. Hold the probe and board locks from `docs/hardware-locking.md` throughout hardware operations. Select the probe by serial, verify `VTref` and `Cortex-M4`; a Cortex-M33 means the SWD wiring is reaching a different chip. Do not retry flash against it.

## Establish the baseline

1. Record board variant, probe serial, SWD pairing, USB identity, and whether double reset enters the `XIAO-BOOT` UF2 drive. Lack of USB alone does not distinguish an absent bootloader from a bad application. Check the board's actual USB supply before the probe; `Found SW-DP` followed by `Failed to power up DAP` can require a probe power cycle with the XIAO powered.
2. Read `build_info.yml`, `zephyr/zephyr.dts`, `.config`, and `zmk.hex`. A normal `xiao_ble` build uses `zephyr,code-partition` at `0x27000`; confirm the ELF/HEX reset vector is there. A CMake `CONFIG_FLASH_LOAD_OFFSET=0x0` override alone does not move the devicetree code partition. Reject an image that overlaps `0x0–0x26fff` or `0xf4000–0xfffff` unless deliberately restoring the boot chain.
3. Read the target **without halting or resetting** first. This command file is an example; replace the serial and use a real file, since `JLinkExe` does not reliably accept `/dev/stdin` as its command file:

   ```text
   SelectEmuBySN <probe-serial>
   device nRF52840_xxAA
   si SWD
   speed 1000
   connect
   mem32 0x00000000, 2
   mem32 0x00001000, 2
   mem32 0x00027000, 2
   mem32 0x000f4000, 2
   mem32 0x10001014, 2
   qc
   ```

   `0x0` contains the MBR vectors, `0x1000` is within S140, `0x27000` is the application start, `0xF4000` is the UF2 bootloader start, and UICR `0x10001014` (`NRFFW[0]`) points the MBR to the bootloader. `0xffffffff` at a vector means erased. The first vector word should be a plausible RAM stack pointer (`0x20000000–0x20040000`); the second should be an odd Thumb address in the corresponding code region. A plausible vector does **not** prove that image works. On a normal XIAO, `NRFFW[0]` should be `0x000f4000`. `NRFFW[1]` at `0x10001018` is often `0x000fe000`; compare to the chosen factory HEX instead of guessing.
4. Before any recovery write, save the existing 1 MiB flash and 4 KiB UICR to a private path and record the hashes, for example `savebin <backup>.bin 0x0 0x100000` and `savebin <uicr>.bin 0x10001000 0x1000`. Backups may contain keyboard settings/identifiers; keep them out of git. A full read may take tens of seconds. The nRF FICR is factory programmed and is not part of these backups.

## Decision table

| Observation | Action before debugging ZMK |
| --- | --- |
| MBR/S140, bootloader, UICR, and bootloader mode work; app is missing, stale, or linked at `0x0` | Keep the working boot chain. Build the normal `xiao_ble` image at `0x27000`; flash `zmk.hex`, reset and run. If old app bytes/settings cause trouble, erase **only** the application partition (`0x27000–0xEC000`) and optionally the ZMK storage partition (`0xEC000–0xF4000`) after preserving settings. Never erase bootloader pages for an app-only problem. |
| Valid bootloader vector at `0xF4000`, but MBR/S140 at `0x0–0x26fff` is erased or demonstrably corrupt | Restore the correct variant's **combined** Seeed `*_bootloader-0.6.2_s140_7.3.0.hex` or a confirmed matching combined image. An `update-*_nosd.uf2` cannot supply MBR/S140. Keep the existing bootloader if only the low region is damaged and you can safely restore that region from a verified matching image. A version difference alone is not corruption. |
| MBR/S140 present, but bootloader vector missing/corrupt, double reset never reaches UF2, or UICR boot address is erased/wrong | Restore the correct variant's combined HEX and its UICR words. Back up first. When partial programming cannot safely fix UICR, use a full chip erase followed immediately by the combined HEX, then verify boot mode before flashing an application. This loses the prior application and settings. |
| SWD access is protected (`APPROTECT`) | A Nordic CTRL-AP recover/full erase may be necessary; it destroys flash and UICR. Confirm the chip and exact combined recovery image are available before doing it. Reconnect and program the factory-style image in the same session. |
| `Cannot connect to the probe/programmer`, missing usbfs node, `VTref=0`, DAP power-up failure, or Cortex-M33 identified | Repair probe pass-through, power order, target power, or SWD routing first. Flash changes cannot fix these conditions. See `jlink-gdb.md` and the setup section of `SKILL.md`. |

The isolated `code_partition`-at-`0x0` overlay in `skills/develop-zmk-module/references/hardware-rig.md` remains a diagnostic workaround for a particular unit. It bypasses an unusable boot chain and is not the starting state for a normal XIAO build. If a factory-style repair has been verified and that specific unit still cannot boot a `0x27000` image, document the evidence before using the overlay.

## Select and check the recovery image

Seeed's [Arduino core bootloader directory](https://github.com/Seeed-Studio/Adafruit_nRF52_Arduino/tree/master/bootloader) provides separate combined HEX files for [XIAO nRF52840](https://github.com/Seeed-Studio/Adafruit_nRF52_Arduino/tree/master/bootloader/Seeed_XIAO_nRF52840) and [XIAO nRF52840 Sense](https://github.com/Seeed-Studio/Adafruit_nRF52_Arduino/tree/master/bootloader/Seeed_XIAO_nRF52840_Sense). Pin a commit and hash the downloaded file; do not substitute an arbitrary nRF52840 bootloader. At Seeed commit `667f05fdaafd01a05d8027d7dbbf1f4e0b137047`, the combined HEX SHA-256 values were:

| Variant | File | SHA-256 |
| --- | --- | --- |
| XIAO nRF52840 | `Seeed_XIAO_nRF52840_bootloader-0.6.2_s140_7.3.0.hex` | `c79c8cf75ebb7abfa53b02fd3584aa9a5aeb8dc1b073f674f4fa162225630c6c` |
| XIAO nRF52840 Sense | `Seeed_XIAO_nRF52840_Sense_bootloader-0.6.2_s140_7.3.0.hex` | `ac654c6cab225a933278c8be09b92b41bc4c044d064bd8c9c3314c1c4a0cc8c8` |

Fetch through a URL pinned to that commit, such as `https://raw.githubusercontent.com/Seeed-Studio/Adafruit_nRF52_Arduino/<commit>/bootloader/<variant>/<file>`, then run `sha256sum <file>` before use. The 0.6.2/S140 7.3.0 combined HEX has records in `0x0–0x26498` (MBR + SoftDevice), `0xF4000–0xFC3D8` (bootloader), `0xFD800–0xFD858` (settings), and UICR `0x10001014–0x1000101C`. It contains no application at `0x27000`. The two variants have different bootloader bytes. A functional newer bootloader need not be downgraded merely to match this image.

Before `loadfile`, inspect the HEX address ranges and compare its MBR/SoftDevice/bootloader bytes with the saved flash where possible. `loadfile` programs only the HEX records and does not remove an old application from other sectors. SEGGER documents `Erase <start> <end>` for a flash range; use it for app-only cleanup only after checking sector boundaries and excluding the bootloader/settings.

For a **full recovery justified by the table**, use Nordic's `nrfutil device program` with `chip_erase_mode=ERASE_ALL` (or `nrfjprog --chiperase` if that is the available Nordic tool). This explicitly erases flash **and UICR**, then programs and verifies the correct variant's combined HEX in one operation. Pin the J-Link serial when more than one probe is attached:

```bash
nrfutil device program --serial-number <probe-serial> \
  --firmware <absolute-path-to-correct-variant-combined.hex> \
  --options chip_erase_mode=ERASE_ALL,verify=VERIFY_READ,reset=RESET_SYSTEM
# Legacy alternative:
nrfjprog --family NRF52 --snr <probe-serial> --program <combined.hex> --chiperase --verify --reset
```

If neither Nordic tool is available, use J-Link only after checking how its `erase` command treats UICR on the installed version. Do not assume a flash-range erase clears UICR. After any recovery, check every command for success; a script reaching `qc` does not prove the flash or verify passed. Re-read the MBR, application, bootloader, and UICR vectors and compare programmed spans to the selected HEX. Confirm double reset reaches the UF2 bootloader and inspect `INFO_UF2.TXT` for board ID/SoftDevice version when available. Then build/flash the normal `0x27000` ZMK image and confirm USB enumeration, Studio RPC, and the intended behavior. `r` plus `go` is essential after any halted inspection; exiting J-Link with the core halted makes a healthy application look frozen.

Sources: [Seeed XIAO BLE guide](https://wiki.seeedstudio.com/XIAO_BLE/), [Seeed board package](https://github.com/Seeed-Studio/Adafruit_nRF52_Arduino), [Adafruit bootloader supported boards](https://github.com/adafruit/Adafruit_nRF52_Bootloader/blob/master/supported_boards.md), [SEGGER Commander command syntax](https://kb.segger.com/J-Link_Commander), [Nordic programming options](https://docs.nordicsemi.com/r/bundle/nrfutil/page/nrfutil-device/guides/programming.html/programming-options).
