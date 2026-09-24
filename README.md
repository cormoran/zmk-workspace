# cormoran's west workspace for ZMK

[![Test ZMK templates](https://github.com/cormoran/zmk-workspace/actions/workflows/zmk-config.yml/badge.svg)](https://github.com/cormoran/zmk-workspace/actions/workflows/zmk-config.yml)

This workspace supports ZMK projects that use different Zephyr and ZMK
versions at the same time. Each shared West profile keeps the dependency set
for one Zephyr commit and ZMK branch, while compatible module worktrees reuse
that profile. It also provides a [Nix](https://nixos.org/) development
environment for ZMK projects. Builds use the
[cormoran/zmk-west-commands](https://github.com/cormoran/zmk-west-commands)
West extension.

## Directory structure

```text
projects/                         Source checkouts used to initialize profiles
└── <repo>/
    └── …                               Source repository

ws/                               Shared West profiles
└── <profile>/
    ├── workspace-config/              Tracked profile manifest and metadata
    ├── zephyr/, zmk/, …                Shared West dependency checkouts
    └── wt-<repo>/<branch>/             Feature-branch Git worktrees
```

Use `projects/<repo>` to clone a module. It is the source used to create a
profile when a new dependency set is needed. `projects/` is ignored by this
repository.

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

Clone the module under `projects/`, then select a compatible shared profile.
Use `check` before creating a worktree to confirm the profile you intend to
use.

```bash
git clone <module-url> projects/<repo>
python3 tools/shared_west.py check <profile> <repo>
```

Create the branch worktree in that profile, and build from the resulting path.
All development builds belong in `ws/<profile>/wt-<repo>/<branch>`.

```bash
python3 tools/shared_west.py worktree <repo> <branch> --profile <profile>
cd ws/<profile>/wt-<repo>/<branch>
west zmk-build tests/zmk-config -m . -d ./build -q
```

Use a separate `build/` directory in every worktree. The module's README
defines its own build target when it differs from `tests/zmk-config`.

### Create a shared profile

If no existing profile is compatible, initialize the source repository's
standalone dependencies according to that module's README. Then create a
profile from `projects/<repo>`:

```bash
python3 tools/shared_west.py init <repo>
```

This creates the shared dependencies under `ws/<profile>`; create a worktree
with the preceding commands before building. Only run dependency updates from
the profile directory. After updating, check the affected modules and rebuild
their worktrees.

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
