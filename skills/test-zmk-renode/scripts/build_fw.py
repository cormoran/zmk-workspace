#!/usr/bin/env python3
"""Build ZMK firmware ELFs for Renode testing.

Wraps `west build` with the exact flags discovered during this skill's
Renode bring-up (see EXPERIMENT_LOG.md / references/renode-notes.md for the
why): USB+QSPI disabled in the devicetree overlay, USB+BLE off in Kconfig,
console/log retargeted to a plain UART, and (for Studio RPC builds) the
Renode-only `ZMK_TRANSPORT_NONE` UART transport module swapped in for the
real (USB-gated, unusable-under-Renode) one.

Two ways to call this:

1. Skill-compat role builds (unchanged behavior, used by renode_test.py /
   the regression gate)::

       python build_fw.py --role single
       python build_fw.py --role central --pristine
       python build_fw.py --role peripheral

   These always target `ZMK_STUDIO_RPC_PERF_DIR` (default
   `zmk-feature-studio-rpc-perf` next to this workspace) and the
   `my_awesome_keyboard` shield -- exactly as before the refactor.

2. Generic builds (used by any module repo, e.g. via the
   `zmk-renode-test` composite action)::

       python build_fw.py \\
           --west-topdir /path/to/module/checkout \\
           --board xiao_ble//zmk \\
           --shield tester_xiao \\
           --zmk-config /path/to/module/tests/zmk-config/config \\
           --module-path /path/to/module \\
           --module-path /path/to/module/tests/zmk-config \\
           --cmake-arg=-DCONFIG_ZMK_STUDIO=y \\
           --cmake-arg=-DCONFIG_ZMK_TEMPLATE_FEATURE=y \\
           --build-dir /path/to/module/build/renode_generic

   The Renode essentials -- overlay, transport module, COMMON_ARGS -- are
   always added automatically, resolved relative to *this script's own
   location* (so it works regardless of which repo's working tree it's
   invoked from). Pass `--overlay split-wired-uart` to use the split-wired
   overlay instead of the default studio-rpc-uart one, or `--overlay
   /custom/path.overlay` for a caller-supplied one; `--no-studio-transport`
   to skip adding the Renode Studio UART transport module + its Kconfig
   (e.g. for a build that doesn't use Studio RPC at all).

Both modes print the built ELF's absolute path on the last line of stdout
so callers can capture it directly.
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent
ZMK_WORKSPACE = SKILL_DIR.parents[1]

OVERLAYS = SKILL_DIR / "overlays"
RENODE_TEST_MODULE = SKILL_DIR / "renode-test-module"

# -- Skill-compat (role-based) defaults -------------------------------------

WEST_TOPDIR = Path(
    os.environ.get("ZMK_STUDIO_RPC_PERF_DIR", ZMK_WORKSPACE / "zmk-feature-studio-rpc-perf")
).resolve()

BOARD = "xiao_ble//zmk"
SHIELD = "my_awesome_keyboard"


def find_zephyr_sdk() -> str | None:
    """Best-effort discovery of a Zephyr SDK install, honoring an existing env var."""
    existing = os.environ.get("ZEPHYR_SDK_INSTALL_DIR")
    if existing and (Path(existing) / "sdk_version").exists():
        return existing

    candidates: list[str] = []
    for root in (Path.home() / "agent-home", Path.home(), Path("/opt")):
        candidates.extend(sorted(glob.glob(str(root / "zephyr-sdk-0.16*"))))
        candidates.extend(sorted(glob.glob(str(root / "zephyr-sdk-*"))))
    for c in candidates:
        if (Path(c) / "sdk_version").exists():
            return c
    return None


def build_env() -> dict:
    env = os.environ.copy()
    env.setdefault("ZEPHYR_TOOLCHAIN_VARIANT", "zephyr")
    sdk = find_zephyr_sdk()
    if sdk:
        env.setdefault("ZEPHYR_SDK_INSTALL_DIR", sdk)
    return env


# Common flags needed by every Renode build: no USB (its HW model hangs
# forever under Renode -- see renode-test-module/Kconfig), no BLE (avoids a
# controller-command-timeout kernel oops we hit with an empty NVS/no
# controller under Renode), console+log wired to a real UART instead of the
# board's default USB-CDC path, and the board's "CDC ACM as serial backend"
# Kconfig cascade turned off (it silently re-enables USB_DEVICE_STACK and
# hangs the same way even with our overlay's DT nodes disabled).
COMMON_ARGS = [
    "-DCONFIG_ZMK_USB=n",
    "-DCONFIG_ZMK_BLE=n",
    "-DCONFIG_BOARD_SERIAL_BACKEND_CDC_ACM=n",
    "-DCONFIG_LOG=y",
    "-DCONFIG_CONSOLE=y",
    "-DCONFIG_UART_CONSOLE=y",
    "-DCONFIG_UART_INTERRUPT_DRIVEN=y",
]

# Flags that swap in the Renode-only ZMK_TRANSPORT_NONE Studio RPC UART
# transport in place of the real (USB-gated) one -- see
# renode-test-module/Kconfig and references/renode-notes.md gotcha #2.
STUDIO_TRANSPORT_ARGS = [
    "-DCONFIG_ZMK_STUDIO_TRANSPORT_UART=n",
    "-DCONFIG_ZMK_RENODE_STUDIO_UART_TRANSPORT=y",
]

OVERLAY_ALIASES = {
    "studio-rpc-uart": OVERLAYS / "studio-rpc-uart.overlay",
    "split-wired-uart": OVERLAYS / "split-wired-uart.overlay",
}

ROLE_CONFIG = {
    "single": {
        "build_dir_name": "renode_single",
        "overlay": OVERLAYS / "studio-rpc-uart.overlay",
        "cmake_args": [
            "-DCONFIG_ZMK_STUDIO=y",
            "-DCONFIG_ZMK_STUDIO_RPC_PERF_HANDLER=y",
            *STUDIO_TRANSPORT_ARGS,
        ],
    },
    "central": {
        "build_dir_name": "renode_split_central",
        "overlay": OVERLAYS / "split-wired-uart.overlay",
        "cmake_args": [
            "-DCONFIG_ZMK_SPLIT=y",
            "-DCONFIG_ZMK_SPLIT_ROLE_CENTRAL=y",
            "-DCONFIG_ZMK_SPLIT_WIRED_UART_MODE_INTERRUPT=y",
        ],
    },
    "peripheral": {
        "build_dir_name": "renode_split_peripheral",
        "overlay": OVERLAYS / "split-wired-uart.overlay",
        "cmake_args": [
            "-DCONFIG_ZMK_SPLIT=y",
            "-DCONFIG_ZMK_SPLIT_WIRED_UART_MODE_INTERRUPT=y",
        ],
    },
}


def _run_west_build(cmd: list[str], cwd: Path, build_dir: Path, quiet: bool) -> Path:
    if not quiet:
        print("running:", " ".join(cmd), file=sys.stderr)

    result = subprocess.run(cmd, cwd=cwd, env=build_env(), capture_output=quiet, text=True)
    if result.returncode != 0:
        if quiet:
            sys.stderr.write(result.stdout or "")
            sys.stderr.write(result.stderr or "")
        raise SystemExit(f"west build failed (exit {result.returncode})")

    elf = build_dir / "zephyr" / "zmk.elf"
    if not elf.exists():
        raise SystemExit(f"build reported success but {elf} is missing")
    return elf


def build(role: str, pristine: bool = False, quiet: bool = False) -> Path:
    """Skill-compat role build -- unchanged behavior/output from before the
    generalization, used by renode_test.py (the regression gate)."""
    if role not in ROLE_CONFIG:
        raise SystemExit(f"unknown role {role!r}, expected one of {sorted(ROLE_CONFIG)}")
    cfg = ROLE_CONFIG[role]

    build_dir = WEST_TOPDIR / "build" / cfg["build_dir_name"]
    zmk_config = WEST_TOPDIR / "tests" / "zmk-config" / "config"
    extra_modules = ";".join(
        str(p) for p in (WEST_TOPDIR / "tests" / "zmk-config", WEST_TOPDIR, RENODE_TEST_MODULE)
    )

    cmd = [
        "west",
        "build",
        "-s",
        str(WEST_TOPDIR / "dependencies" / "zmk" / "app"),
        "-d",
        str(build_dir),
        "-b",
        BOARD,
        "-p",
        "always" if pristine else "auto",
        "--",
        f"-DSHIELD={SHIELD}",
        f"-DZMK_CONFIG={zmk_config}",
        f"-DZMK_EXTRA_MODULES={extra_modules}",
        f"-DEXTRA_DTC_OVERLAY_FILE={cfg['overlay']}",
        *COMMON_ARGS,
        *cfg["cmake_args"],
    ]

    return _run_west_build(cmd, cwd=WEST_TOPDIR, build_dir=build_dir, quiet=quiet)


def build_generic(
    *,
    west_topdir: Path,
    board: str = BOARD,
    shield: str | None,
    zmk_config: Path | None,
    zmk_app: Path | None = None,
    module_paths: list[Path] | None = None,
    cmake_args: list[str] | None = None,
    overlay: str = "studio-rpc-uart",
    extra_dtc_overlays: list[Path] | None = None,
    studio_transport: bool = True,
    build_dir: Path | None = None,
    pristine: bool = False,
    quiet: bool = False,
) -> Path:
    """Generic Renode build for any module repo's own west workspace.

    `west_topdir` is that repo's own west workspace root (its `.west/`
    dir's parent -- typically the repo checkout itself for a module with an
    embedded workspace, per this template's layout). `module_paths` should
    include the module repo itself and any `ZMK_EXTRA_MODULES` entries it
    needs (its own tests/zmk-config dir, sibling feature modules, ...) --
    this script always appends `renode-test-module` (the Renode Studio UART
    transport) on top of whatever the caller passes, unless
    `studio_transport=False`.
    """
    west_topdir = Path(west_topdir).resolve()
    zmk_app = Path(zmk_app) if zmk_app else west_topdir / "dependencies" / "zmk" / "app"

    overlay_path = OVERLAY_ALIASES.get(overlay)
    if overlay_path is None:
        overlay_path = Path(overlay)
    if not overlay_path.is_file():
        raise SystemExit(f"overlay not found: {overlay_path}")

    modules = list(module_paths or [])
    if studio_transport:
        modules.append(RENODE_TEST_MODULE)
    extra_modules = ";".join(str(p) for p in modules)

    dtc_overlays = [overlay_path, *(extra_dtc_overlays or [])]

    if build_dir is None:
        build_dir = west_topdir / "build" / "renode_generic"
    build_dir = Path(build_dir)

    cmd = [
        "west",
        "build",
        "-s",
        str(zmk_app),
        "-d",
        str(build_dir),
        "-b",
        board,
        "-p",
        "always" if pristine else "auto",
        "--",
    ]
    if shield:
        cmd.append(f"-DSHIELD={shield}")
    if zmk_config:
        cmd.append(f"-DZMK_CONFIG={zmk_config}")
    if extra_modules:
        cmd.append(f"-DZMK_EXTRA_MODULES={extra_modules}")
    cmd.append(f"-DEXTRA_DTC_OVERLAY_FILE={';'.join(str(p) for p in dtc_overlays)}")
    cmd.extend(COMMON_ARGS)
    if studio_transport:
        cmd.extend(STUDIO_TRANSPORT_ARGS)
    cmd.extend(cmake_args or [])

    return _run_west_build(cmd, cwd=west_topdir, build_dir=build_dir, quiet=quiet)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--role",
        choices=sorted(ROLE_CONFIG),
        help="skill-compat role build (single/central/peripheral); mutually "
        "exclusive with the generic options below",
    )
    ap.add_argument("--pristine", action="store_true", help="force a clean rebuild")
    ap.add_argument("--quiet", action="store_true", help="only print the resulting ELF path")

    # Generic-mode options.
    ap.add_argument("--west-topdir", type=Path, help="module repo's west workspace root")
    ap.add_argument("--zmk-app", type=Path, default=None, help="override the -s app dir")
    ap.add_argument("--board", default=BOARD)
    ap.add_argument("--shield")
    ap.add_argument("--zmk-config", type=Path)
    ap.add_argument(
        "--module-path",
        action="append",
        default=[],
        dest="module_paths",
        help="extra ZMK_EXTRA_MODULES entry; repeatable",
    )
    ap.add_argument(
        "--cmake-arg",
        action="append",
        default=[],
        dest="cmake_args",
        help="extra -D... cmake arg; repeatable",
    )
    ap.add_argument(
        "--overlay",
        default="studio-rpc-uart",
        help="'studio-rpc-uart' (default), 'split-wired-uart', or a path to a custom overlay",
    )
    ap.add_argument(
        "--extra-dtc-overlay",
        action="append",
        default=[],
        dest="extra_dtc_overlays",
        type=Path,
        help="additional EXTRA_DTC_OVERLAY_FILE entry (appended after the Renode overlay); repeatable",
    )
    ap.add_argument(
        "--no-studio-transport",
        action="store_false",
        dest="studio_transport",
        help="skip adding the Renode Studio-RPC UART transport module + Kconfig",
    )
    ap.add_argument("--build-dir", type=Path)

    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.role:
        elf = build(args.role, pristine=args.pristine, quiet=args.quiet)
    else:
        if not args.west_topdir:
            raise SystemExit("either --role or --west-topdir is required")
        elf = build_generic(
            west_topdir=args.west_topdir,
            board=args.board,
            shield=args.shield,
            zmk_config=args.zmk_config,
            zmk_app=args.zmk_app,
            module_paths=[Path(p) for p in args.module_paths],
            cmake_args=args.cmake_args,
            overlay=args.overlay,
            extra_dtc_overlays=args.extra_dtc_overlays,
            studio_transport=args.studio_transport,
            build_dir=args.build_dir,
            pristine=args.pristine,
            quiet=args.quiet,
        )

    print(str(elf))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
