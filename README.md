# cormoran's west workspace for ZMK

[![Build with zmk#main](https://github.com/cormoran/zmk-workspace/actions/workflows/zmk-config.yml/badge.svg)](https://github.com/cormoran/zmk-workspace/actions/workflows/zmk-config.yml)
[![Build with zmk#v0.3](https://github.com/cormoran/zmk-workspace/actions/workflows/zmk-config-v0.3.yml/badge.svg)](https://github.com/cormoran/zmk-workspace/actions/workflows/zmk-config-v0.3.yml)

- Minium zephyr SDK setup with [Nix](https://nixos.org/)
- Making use of thin west sub-command [cormoran/zmk-west-commands](https://github.com/cormoran/zmk-west-commands) for building ZMK

## Usage

1. Install [nix](https://nixos.org/download/)
2. `./init.sh`
3. Initialize your zmk-config and build

   Example with [cormoran/zmk-config-template](https://github.com/cormoran/zmk-config-template).

   ```bash
   $ west init -m https://github.com/cormoran/zmk-config-template --mf config/west-workspace.yml # --mr v0.3-branch
   $ west update --narrow
   $ west zephyr-export
   $ west zmk-build  ./zmk-config-template/ -q
   ```

   Example with [cormoran/zmk-module-template](https://github.com/cormoran/zmk-module-template).

   ```bash
   $ west init -m https://github.com/cormoran/zmk-module-template --mf west/west-test-workspace.yml # --mr v0.3-branch
   $ west update --narrow
   $ west zephyr-export
   $ python -m unittest
   ```

   Or ZMK official zmk-config

   ```bash
   $ west init -m https://github.com/zmkfirmware/unified-zmk-config-template --mf config/west.yml
   $ west update --narrow
   $ west zephyr-export
   $ west build -b nice_nano -- -DSHIELD=kyria_left \
      -DZMK_CONFIG="$(pwd)/unified-zmk-config-template/config"
   ```

   Tips: `zmk-build` sub command is provided by [cormoran/zmk-west-commands](https://github.com/cormoran/) west module.

To re-initialize with other zmk-config, module, `rm -r .west` and do step3 again.

## Hardware

Some modules/features in this workspace are validated on real hardware
(J-Link + Seeed XIAO nRF52840, split-keyboard debugging, etc.) inside an
LXC/LXD container. See [docs/hardware-rig.md](docs/hardware-rig.md) for how
that rig is set up, if you want to reproduce something similar.

## Acknowledgment

Setup with nix is based on below works by @urob and @kot149

- https://github.com/kot149/zmk-workspace
- https://github.com/urob/zmk-config
