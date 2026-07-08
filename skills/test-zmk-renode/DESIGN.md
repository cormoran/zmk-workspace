# test-zmk-renode — Design & Bring-up Plan

Goal: test a **XIAO nRF52840** ZMK keyboard in the **Renode** emulator, with no
physical hardware, covering:

- **Studio RPC** over **USB** and over **BLE**
- **Split** keyboard over **wired** and over **BLE**

Renode is a functional (not cycle-accurate) full-system emulator. It ships an
nRF52840 platform (`platforms/cpus/nrf52840.repl`) and runs the exact same
Zephyr/ZMK `.elf` that would run on hardware. Multiple emulated boards run in one
Renode process as separate *machines*; their UARTs and radios can be wired
together, which is what makes split testing possible without hardware.

## What is realistically emulable (tiers)

Renode models peripherals functionally. Not every transport is equally easy:

| Tier | Path | Renode mechanism | Confidence |
|------|------|------------------|------------|
| **T1** | Studio RPC over UART (stands in for **USB**) | one machine, ZMK `zmk,studio-rpc-uart` bound to a hardware UART, UART exposed on a TCP socket the harness drives | High |
| **T2** | Split over **wired** (UART) | two machines, central TX↔peripheral RX cross-wired via a Renode UART hub; a third UART per board carries console + Studio RPC | Medium-High |
| **T3** | Studio RPC over **BLE**, split over **BLE** | two machines' `radio` peripherals joined by a Renode `BLEMedium`/wireless medium; host-side BLE central is the hard part | Experimental |

### USB vs UART note (important)

On real hardware Studio-over-USB uses a USB-CDC-ACM endpoint (the
`studio-rpc-usb-uart` snippet). Renode's nRF52840 USBD device model does not
present a host-visible CDC ACM port the test harness can open. **In emulation we
bind `zmk,studio-rpc-uart` to a real hardware UART** (UARTE) and expose that UART
on a TCP socket. The RPC byte stream and framing are identical to the USB path —
only the physical carrier differs. The skill documents this substitution
explicitly; it is the pragmatic "USB" stand-in and is the primary, always-green
transport. Real USB-CDC enumeration is out of scope for Renode.

## Components (files in this skill)

```
scripts/
  install_renode.sh   # fetch + unpack Renode portable tarball to $RENODE_HOME
  build_fw.py         # west build XIAO nRF52840 fw (board xiao_ble) → .elf, per role/transport
  rpc_client.py       # ZMK Studio RPC framing over a TCP socket (Renode UART) — reused framing
  renode_test.py      # orchestrator: build → launch Renode headless → drive RPC/split → assert
platforms/
  xiao_nrf52840.repl  # platform desc (base nRF52840 + any XIAO-specific wiring the tests need)
  single.resc         # T1: one machine, RPC UART on a socket
  split_wired.resc    # T2: central + peripheral, UARTs cross-wired
  split_ble.resc      # T3 (experimental): two machines + wireless medium
overlays/
  studio-rpc-uart.overlay  # bind zmk,studio-rpc-uart to a hw UART (Renode-friendly, no USB)
references/
  renode-notes.md     # gotchas discovered during bring-up
EXPERIMENT_LOG.md     # running log of what worked / failed during bring-up
```

## Firmware build

Build against the already-set-up west workspace in
`../../zmk-feature-studio-rpc-perf` (it has `zmk` + `zephyr` + deps under
`dependencies/`). Board is ZMK `xiao_ble`. The studio-rpc-perf shield
`my_awesome_keyboard` (and its split central/peripheral variants) is a ready
Studio-RPC-enabled target. Produce `.elf` (Renode loads ELF, not uf2).

## Bring-up ladder (do in order, commit green tiers as you go)

1. **T0 boot** — build any XIAO nRF52840 ZMK `.elf`, load in Renode, confirm it
   boots to the ZMK banner on the console UART. Proves platform + elf load.
2. **T1 Studio-over-UART** — add the UART RPC overlay, expose UART on a socket,
   have `rpc_client.py` complete a Studio RPC round-trip (e.g. GetDeviceInfo or
   the studio-rpc-perf ping). This is the first must-pass test.
3. **T2 wired split** — two machines, wired-UART split, confirm the central sees
   the peripheral (split connection up) and a Studio RPC that relays to the
   peripheral succeeds.
4. **T3 BLE (experimental)** — attempt BLE split and/or Studio-over-BLE via a
   Renode wireless medium. If Zephyr's BLE controller does not come up under
   Renode, document precisely where it breaks and leave the test `skipUnless`-gated.

## Success criteria for the PR

- T1 green and runnable via a single `python renode_test.py` (or `python -m unittest`).
- T2 green **or** a documented, reproducible reason it cannot pass under Renode.
- T3 attempted; either green or clearly documented as experimental/skipped.
- Skill (`SKILL.md`) explains setup, how to run, transport substitutions, and gotchas.
