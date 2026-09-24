# cormoran's west workspace for ZMK

[![Test ZMK templates](https://github.com/cormoran/zmk-workspace/actions/workflows/zmk-config.yml/badge.svg)](https://github.com/cormoran/zmk-workspace/actions/workflows/zmk-config.yml)

This workspace provides a [Nix](https://nixos.org/) development environment for
ZMK projects and tools for sharing a compatible West dependency checkout among
module worktrees. Builds use the
[cormoran/zmk-west-commands](https://github.com/cormoran/zmk-west-commands)
West extension.

## Directory structure

```text
.
├── docs/       Documentation for the workspace and hardware setup
├── nix/        Nix development-shell definition
├── projects/   Standalone source checkouts used to initialize profiles
│   └── <repo>/
│       ├── .west/ and dependencies/   Initial standalone West workspace
│       └── …                           Source repository
├── tools/      Workspace utilities, including shared_west.py
├── ws/         Shared West profiles
│   └── <profile>/
│       ├── workspace-config/          Tracked profile manifest and metadata
│       ├── zephyr/, zmk/, …            Shared West dependency checkouts
│       └── wt-<repo>/<branch>/         Feature-branch Git worktrees
└── zephyr/     Workspace Zephyr module metadata
```

Use `projects/<repo>` to clone a module and initialize its standalone West
workspace. It is the source used to create a profile, and it remains available
for standalone development. `projects/` is ignored by this repository.

Use `ws/<profile>` for shared-profile development. A profile owns one set of
West dependency checkouts. Create each feature branch in
`wt-<repo>/<branch>`; compatible branches then build against the same
dependencies. Only `workspace-config/` is tracked by this repository. The
dependencies and worktrees are local files.

## Usage

Install [Nix](https://nixos.org/download/), then clone this repository and
enter its development shell:

```bash
git clone https://github.com/cormoran/zmk-workspace.git
cd zmk-workspace
./init.sh
```

`./init.sh` is a shortcut for `nix develop ./nix`. Run the remaining commands
from that shell.

### Start a module

Clone a module under `projects/` and initialize its standalone dependency tree.
The manifest filename belongs to the module; this example uses
[zmk-module-template](https://github.com/cormoran/zmk-module-template).

```bash
git clone https://github.com/cormoran/zmk-module-template.git projects/zmk-module-template
cd projects/zmk-module-template
west init -l west --mf west-test-isolated.yml
west update --narrow
west zephyr-export
cd ../..
```

Follow the selected project's README for its manifest and standalone build
commands. Config repositories can remain standalone when a shared profile is
not needed.

### Create and use a shared profile

Create a profile once from an initialized module. The command records the
module's compatible dependency set in `ws/`.

```bash
python3 tools/shared_west.py init zmk-module-template
```

Create a feature worktree. The command finds a compatible profile, verifies the
module's active dependencies, and prints the worktree path.

```bash
python3 tools/shared_west.py worktree zmk-module-template my-feature
cd ws/<profile>/wt-zmk-module-template/my-feature
west zmk-build tests/zmk-config -m . -d ./build -q
```

Use a separate `build/` directory in every worktree. To inspect a specific
profile before creating a branch, run:

```bash
python3 tools/shared_west.py check <profile> zmk-module-template
```

Only run dependency updates from the profile directory. After updating, check
the affected modules and rebuild their worktrees:

```bash
cd ws/<profile>
west update zmk
python3 ../../tools/shared_west.py check <profile> zmk-module-template
```

Use `python3 tools/shared_west.py --help` for `--start`, `--manifest`, and
`--profile`. For the profile design and its constraints, see
[shared West profile experiment](docs/shared-west-experiment.md).

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
