---
name: develop-zmk-web-ui
description: Develop and verify a ZMK module Web UI (React/Vite plus Studio RPC or Web Serial). Use for changes under a module's web/ directory, especially connection, RPC loading, generated protobuf, or browser reload/render-loop issues.
---

# Develop a ZMK Module Web UI

## Scope and setup

Use this skill for a module's `web/` frontend. Read `web/package.json`,
`web/README.md`, the generated-proto configuration, and the web CI workflow
before changing code. Use the module's compatible shared-West worktree; see
`$shared-west-profiles` before any paired firmware work.

Install dependencies only when `node_modules` is absent or the lockfile
changed. This workspace's packages can use git dependencies, so use the
repository-approved form when needed:

```bash
cd web
NPM_CONFIG_ALLOW_GIT=all npm ci
```

## Prevent render and reload loops

First distinguish a browser navigation (`location`, a form submit, Vite HMR)
from a React/RPC loop. For a UI that appears to reload repeatedly, inspect
`useEffect`, `useCallback`, `useMemo`, timers, reconnect logic, and every
state update that each effect starts. A request or state update followed by a
render is enough to create a loop even when `window.location.reload()` is
never called.

For `@cormoran/zmk-studio-react-hook` in particular:

- `useCustomSubsystem()` may return a fresh `subsystem` object on every
  render. Do not make a loader or notification effect depend on that object;
  derive and depend on the scalar `subsystem?.index` instead.
- Keep a protobuf codec passed to `useCustomSubsystem()` stable. Define a
  static codec outside the component or memoize it; an inline object recreates
  the hook's `call` callback, which recreates loaders and can retrigger their
  effects indefinitely.
- Use complete effect dependencies after making their inputs stable. Do not
  suppress `react-hooks/exhaustive-deps` to mask an unstable dependency.
- Web Serial `autoReconnect` is separate from an application render loop.
  Confirm it performs only the intended reconnect attempt and never makes a
  failed reconnect trigger application state that restarts it.

Add a regression test for every fixed loop. Drive a successful connection,
allow the initial RPC loaders to settle, and assert their call count remains
unchanged after their state updates. The test must fail if a re-render starts
the loaders again; merely checking that the first screen rendered is not
sufficient.

## Generated API and deployment safety

Run `npm run generate` after changing proto files, `buf.gen.yaml`, or RPC
contracts, and review generated TypeScript for the intended fields. Do not
hand-edit generated files.

Use `VITE_BASE=/` for a root-hosted preview/PR build. GitHub Pages project
sites use `VITE_BASE=/<repository-name>/`; verify that build too when the
default base or assets/routes change. Keep external links and forms from
navigating the current application unless navigation is intentional.

## Required pre-commit verification

For every Web UI change, run these from `web/` before committing (after
regenerating dependencies if required):

```bash
npm run generate
npm run lint
npm test -- --runInBand
VITE_BASE=/ npm run build
VITE_BASE=/$(basename "$(git rev-parse --show-toplevel)")/ npm run build
```

For a connection, loader, or rendering change, also inspect the loop-specific
test's RPC/reconnect counts and start `npm run dev` for a short browser smoke
test when a Chromium browser is available. Confirm one initial loader pass,
no repeating network/RPC requests, and no full-page navigation. Stop the dev
server when finished.

Do not commit until the applicable commands and regression tests pass. If CI
fails, retrieve the failed Web UI job log, reproduce its exact command and
`VITE_BASE`, make the smallest scoped correction, then push and monitor the
replacement check to completion.
