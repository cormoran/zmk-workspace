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
    ├── workspace-config/              Local profile manifest and metadata
    ├── zephyr/, zmk/, …                Shared West dependency checkouts
    └── wt-<repo>/<branch>/             Feature-branch Git worktrees
```

Use `projects/<repo>` to clone a module. It is the source used to create a
profile when a new dependency set is needed. `projects/` is ignored by this
repository.

Use `ws/<profile>` for shared-profile development. A profile owns one set of
West dependency checkouts. Create each feature branch in
`wt-<repo>/<branch>`; compatible branches then build against the same
dependencies. All profile files are local and ignored by this repository.

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

Clone the module under `projects/`, then use `find` to list compatible shared
profiles. Select one of the printed profile names. If `find` reports that no
profile is compatible, create one before continuing.

```bash
git clone <module-url> projects/<repo>
python3 tools/shared_west.py find <repo>
```

#### When no profile is compatible

Initialize the source repository's standalone dependencies according to that
module's README. Then create a profile from `projects/<repo>`:

```bash
python3 tools/shared_west.py init <repo>
```

This only creates shared dependencies under `ws/<profile>`; do not build in
the source checkout. Use the printed profile path in the next step.

#### Create and build the worktree

Create the branch worktree in the selected or newly created profile, and build
from the resulting path. `worktree` checks the selected profile again. All
development builds belong in `ws/<profile>/wt-<repo>/<branch>`.

```bash
python3 tools/shared_west.py worktree <repo> <branch> --profile <profile>
cd ws/<profile>/wt-<repo>/<branch>
west zmk-build tests/zmk-config -m . -d ./build -q
```

Use a separate `build/` directory in every worktree. The module's README
defines its own build target when it differs from `tests/zmk-config`. Only run
West dependency updates from the profile directory, then recheck and rebuild
the affected worktrees.

### Change dependency versions

Changing an active revision in a module's West manifest, including ZMK or
Zephyr, requires a new shared profile. Do not change the current profile's
`workspace-config/` or run `west update` in the feature worktree to force the
new version.

First commit the manifest change in the existing worktree. Create a temporary
standalone seed checkout at that commit under `projects/`, initialize the
dependencies required by its complete test manifest, and create a profile from
that seed:

```bash
python3 tools/shared_west.py init <seed-checkout> --manifest <complete-test-manifest>
```

The command prints the new profile path. Create a successor branch from the
manifest-change commit in that profile, then build there:

```bash
python3 tools/shared_west.py worktree <repo> <successor-branch> \
  --start <manifest-change-commit> --profile <new-profile>
cd ws/<new-profile>/wt-<repo>/<successor-branch>
west zmk-build tests/zmk-config -m . -d ./build -q
```

Using a successor branch keeps the old worktree available for comparison. To
keep the same branch name, commit its changes, remove its old worktree, and
then run `worktree` with that branch and the new profile. Remove the temporary
seed checkout after the new profile has been created.

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
