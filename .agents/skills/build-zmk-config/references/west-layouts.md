# ZMK west Workspace Layouts

## Clone-root layout

Goal: each cloned zmk-config is its own west topdir.

Use when parallel builds matter or when the config supports an isolated manifest.

Common commands:

```bash
cd <zmk-config>
west init -l config --mf west-isolated.yml
west update --narrow
west zephyr-export
west zmk-build -d ./build -q
```

If `config/west.yml` imports `west-isolated.yml`, `west init -l config` is also valid.

Official-style clone-root configs may only provide `config/west.yml` with:

```yaml
self:
  path: config
```

For those, use:

```bash
cd <zmk-config>
west init -l config
west update --narrow
west zephyr-export
```

Expected shape:

```text
<zmk-config>/
  .west/
  build.yaml
  build/
  config/
  dependencies/
```

Use `west topdir` after init. It must print `<zmk-config>`.

If the config lacks `zmk-west-commands`, build manually with `west build -s "$(west list zmk -f '{abspath}')/app" ...`.

## Repository-root layout

Goal: the surrounding zmk-workspace directory is the west topdir, and the config is one project inside it.

Use only when the config or workspace instructions explicitly expect it.

Common commands from the zmk-workspace root:

```bash
west init -m <repo-url> --mf config/west-workspace.yml
west update --narrow
west zephyr-export
west zmk-build ./<config-dir>/ -q
```

Expected shape:

```text
<zmk-workspace>/
  .west/
  <zmk-config>/
  zmk/
  zephyr/
  modules/
```

## Pitfall

`west init -l . --mf config/west-workspace.yml` from inside a config clone may create `.west` in the clone's parent. That is a repository-root workspace with the parent as topdir, not a clone-root workspace.
