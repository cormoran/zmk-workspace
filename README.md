# cormoran's west workspace for ZMK

[![Test ZMK templates](https://github.com/cormoran/zmk-workspace/actions/workflows/zmk-config.yml/badge.svg)](https://github.com/cormoran/zmk-workspace/actions/workflows/zmk-config.yml)

- Minium zephyr SDK setup with [Nix](https://nixos.org/)
- Making use of thin west sub-command [cormoran/zmk-west-commands](https://github.com/cormoran/zmk-west-commands) for building ZMK

## Codex setup

Launch Codex from this repository root and trust the project so it loads
[`.codex/config.toml`](.codex/config.toml). The project config gives Codex the
shared West worktree rule. Repository skills in [`.agents/skills/`](.agents/skills/)
are discovered automatically; the detailed dependency and worktree workflow is
in [`shared-west-profiles`](.agents/skills/shared-west-profiles/SKILL.md).
The remaining repository change and local output rules are in [AGENTS.md](AGENTS.md).

CI tests both `main` and `v0.3-branch` for the config and module templates in
one matrix. Each job clones the source into `projects/<repo>`, installs West
dependencies in its own `ws/ci-<repo>-<branch>` workspace, then creates and
builds or tests `ws/ci-<repo>-<branch>/wt-<repo>/<branch>`. The West cache stores
only dependency checkouts inside that CI workspace, not source worktrees or
the workspace configuration.

When launching Codex from a separate Git repository under `projects/` or from
one of its worktrees, launch from this root first if the shared workspace rule
is needed. Those nested repositories have their own Git root and do not inherit
this repository's project configuration.

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

## Shared West profiles for module worktrees

For modules with a standalone West workspace and downloaded `dependencies/`,
`tools/shared_west.py` creates a shared profile. Its name contains the checked
out Zephyr commit and the **ZMK branch name**. ZMK can advance when the profile
is explicitly updated; the other dependencies are pinned to the commits
installed when the profile is created.

```bash
python3 tools/shared_west.py init projects/zmk-behavior-runtime-sensor-rotate
python3 tools/shared_west.py worktree zmk-behavior-runtime-sensor-rotate my-feature
```

The second command places a new or existing `my-feature` branch under
`ws/<profile>/wt-zmk-behavior-runtime-sensor-rotate/my-feature`. Source Git
checkouts live in `projects/<repo>`, and shared West workspaces live in
`ws/<profile>`. The profile's `workspace-config/west.yml` and `profile.json`
are tracked by this repository; dependencies and worktrees are ignored.
An existing branch
must not already be checked out elsewhere. The command checks all active
dependency declarations before placing the worktree. If no compatible profile
exists, it stops without changing shared dependencies. To provision another
profile, initialize one from a matching standalone module workspace.
Run `python3 tools/shared_west.py --help` for `check`, `--start`, and
`--manifest` options. When several profiles satisfy the same declarations,
pass `--profile <profile-name>` to select the intended dependency baseline.

From the new worktree, `west topdir` points at the shared profile. Use a
separate build directory per worktree:

```bash
west zmk-build tests/zmk-config -m . -d ./build -q
```

Only update shared dependencies from the profile directory. For example,
`west update zmk` advances its ZMK branch; then run `shared_west.py check` and
the affected modules' build tests before continuing work. Each module keeps
its standalone manifest, so a checkout outside a shared profile can still be
initialized on its own. The generated profile's `workspace-config/west.yml`
records the dependency commits. Trial details are in
[`docs/shared-west-experiment.md`](docs/shared-west-experiment.md).

## Hardware

Some modules/features in this workspace are validated on real hardware
(J-Link + Seeed XIAO nRF52840, split-keyboard debugging, etc.) inside an
LXC/LXD container. See [docs/hardware-rig.md](docs/hardware-rig.md) for how
that rig is set up, if you want to reproduce something similar. The rig is
shared between concurrent agent sessions — anything touching it must follow
the lock protocol in [docs/hardware-locking.md](docs/hardware-locking.md)
(helper: [tools/hw-lock](tools/hw-lock)).

## Acknowledgment

Setup with nix is based on below works by @urob and @kot149

- https://github.com/kot149/zmk-workspace
- https://github.com/urob/zmk-config
