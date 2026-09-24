# West layouts for ZMK configs

## Config under zmk-workspace

Follow `$shared-west-profiles` first. Clone the source into
`projects/<repo>` and select or create a compatible profile from the
config's complete active manifest. Put a branch worktree at
`ws/<profile>/wt-<repo>/<branch>`. `west topdir` from that worktree must name
the profile; `west list zmk -f '{abspath}'` must name its ZMK checkout. Build
with `-d ./build` in the worktree. The source checkout is for provisioning,
not feature builds.

`shared_west.py` accepts `--manifest config/<file>.yml` for layouts it can
resolve. Its current profile creation expects a complete manifest containing
ZMK and Zephyr, and dependency paths under `dependencies/`. Some official
configs use different paths or import structures; a failed compatibility or
layout check does not authorize changing a populated shared profile. Report
the unsupported layout and extend the helper if that is in scope.

Do not run `west init` or `west update` in a shared worktree. An existing
standalone source checkout with its own `.west` remains standalone until a
new worktree is created in a compatible profile.

## Standalone layout outside a shared profile

Use this for an external repo or for a temporary seed checkout when creating
a new shared profile. For a config with `config/west-isolated.yml`:

```bash
cd <zmk-config>
west init -l config --mf west-isolated.yml
west update --narrow
west zephyr-export
west topdir
```

For an official-style config with `self: path: config` in `config/west.yml`,
use `west init -l config` instead. The clone is the West topdir in these
standalone layouts. Locate the ZMK app with
`west list zmk -f '{abspath}'`; do not assume a fixed `dependencies/zmk`
path.

`west init -l . --mf config/west-workspace.yml` from a config clone can
initialize its parent as topdir. Check `west topdir` before any build or
dependency update.
