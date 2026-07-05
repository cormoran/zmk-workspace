# Hardware locking (shared rig, concurrent agents)

The rig described in [hardware-rig.md](hardware-rig.md) — two SEGGER J-Link
probes and two XIAO test boards — is a single shared physical resource, while
multiple agent sessions (Claude/Codex, possibly in separate git worktrees) may
run in this workspace at the same time. Two sessions driving the same probe or
board concurrently corrupt each other's work: a flash mid-RPC, a halt during
someone else's RTT capture, competing `JLinkExe` connections. Every skill that
touches hardware therefore uses one cooperative lock protocol, implemented by
[`tools/hw-lock`](../tools/hw-lock).

Locks are **advisory**: they only work because every agent follows this
protocol. Never bypass it "just for one quick command".

## The mechanism

- Lock directory: `~/.zmk-hw-locks` (override with `ZMK_HW_LOCK_DIR`). A fixed
  absolute path, deliberately outside any git worktree, so all sessions on
  this machine share it.
- One file per hardware resource; **the file name is the resource name**, the
  content records who holds it:

  ```
  owner=<session id>
  acquired=2026-07-05T10:00:00Z
  task=flash split central
  ```

- The file's **mtime is the heartbeat**. The holder refreshes it with `touch`
  while using the hardware. A lock whose mtime is older than
  `ZMK_HW_LOCK_STALE_SECONDS` (default 600 s = 10 min) is **stale** and may be
  reclaimed by anyone — this is what keeps a crashed/killed session from
  blocking the rig forever.
- Acquisition is atomic (`noclobber` file creation), stale reclaim is atomic
  (`mv` the stale file aside — only one contender's `mv` succeeds — then
  create normally). Multi-resource acquisition happens in sorted order with
  rollback on failure, so two agents grabbing overlapping sets cannot
  deadlock.

## Resource names

Derived mechanically from the udev-managed device nodes
(`/dev/zmk-hp-<class>-<kind>-<serial>-<interface>`): the resource name is
`<class>-<serial>`.

- `jlink-<serial>` — one per J-Link probe (same serial `ShowEmuList` prints,
  as spelled in the device node name, leading zeros included).
- `zmk-<serial>` — one per ZMK board USB identity (covers all of that board's
  tty/hidraw/input nodes).

`tools/hw-lock list` enumerates them. On a machine without the
`/dev/zmk-hp-*` naming scheme, fall back to `jlink-<ShowEmuList serial>` and
lock those names by convention.

## What to lock

- Any J-Link operation (`JLinkExe`, `JLinkGDBServer*`, flash, halt, RTT):
  lock that probe's `jlink-<serial>` **and** the `zmk-<serial>` of the board
  it is SWD-wired to — flashing/reset/halt disturbs the board's USB side too,
  so an RPC-only agent holding just the board lock is protected.
- Board-USB-only work (Studio RPC over `/dev/zmk-hp-zmk-tty-*`, hidraw,
  watching enumeration): lock that board's `zmk-<serial>`.
- Split debugging, or any time you don't yet know which serial maps to which
  physical unit (probe↔board pairing is discovered empirically): **lock
  everything** — `tools/hw-lock acquire $(tools/hw-lock list --names)` — and
  release what you don't need once identified. When in doubt, lock the whole
  rig; with only two units the lost parallelism is cheap compared to a
  corrupted debug session.
- A freshly flashed board can enumerate with a `zmk-<serial>` node that did
  not exist before the flash. That serial belongs to you: acquire it as soon
  as it appears (you already hold the probe, so nobody else can race you for
  the board itself).

## Protocol

```bash
HW="$ZMK_WORKSPACE"/tools/hw-lock     # or path to this repo's tools/hw-lock

"$HW" list                                        # what exists, what's free
"$HW" acquire --owner "$SID" --task "<goal>" jlink-<serial> zmk-<serial>
# ... hardware work ...
"$HW" touch --owner "$SID" jlink-<serial> zmk-<serial>   # heartbeat
# ... more hardware work ...
"$HW" release --owner "$SID" --all                # the moment hardware work ends
```

1. **Acquire before the first command that touches hardware** — including
   "harmless" ones like `ShowEmuList` probing or opening a serial port.
2. **Heartbeat**: run `touch` at the start of each batch of hardware commands,
   and at least every 3 minutes while you still intend to use the hardware
   (builds, analysis, and thinking time count — the lock goes stale at 10
   minutes regardless of why you were quiet). If `touch` fails with "lost
   lock", stop hardware work immediately and re-acquire before continuing.
3. **Release as soon as hardware work ends** — don't hold locks across long
   pure-software phases (builds, code edits, report writing); re-acquire for
   the next hardware step instead.
4. **Blocked?** `acquire` fails fast and tells you the holder and lock age.
   Either retry with `--wait <seconds>` (it polls until the deadline), work on
   something that doesn't need hardware, or report the contention to the user.
   Never delete or overwrite another owner's fresh lock, and never work
   around a held lock by talking to the hardware anyway.

## Owner id

The owner string must be **stable for your whole session** and unique across
concurrent sessions. `hw-lock` resolves it in this order:

1. `--owner <id>` argument
2. `$ZMK_HW_LOCK_OWNER`
3. `$CLAUDE_SESSION_ID` (when the harness exports it)
4. an id generated once and persisted in `$TMPDIR`, when `$TMPDIR` is
   session-scoped

In environments where none of 2–4 exist (common: env vars don't persist
across tool calls), pick an id once at the start of hardware work — your
session id if you know it, else your worktree/branch name (e.g.
`upbeat-robinson-d489c5`), else a random string you write down — and pass the
same `--owner` on **every** call. Two calls with different owners are two
different agents as far as the protocol is concerned.
