#!/usr/bin/env python3
"""Build XIAO nRF52840 ZMK firmware ELFs for Renode testing.

Wraps `west build` with the exact flags discovered during Renode bring-up
(see EXPERIMENT_LOG.md / references/renode-notes.md for the why). Produces
one ELF per (role, transport) combination the test tiers need:

  single    - T0/T1: one board, console on uart0, Studio RPC on uart1.
  central   - T2: split central, console on uart0, wired-split link on uart1.
  peripheral- T2: split peripheral, console on uart0, wired-split link on uart1.

Usage:
    python build_fw.py --role single
    python build_fw.py --role central --pristine
    python build_fw.py --role peripheral

Prints the built ELF's absolute path on the last line of stdout so callers
(renode_test.py) can capture it directly.
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
ZMK_WORKSPACE = SKILL_DIR.parents[1]
WEST_TOPDIR = Path(
    os.environ.get("ZMK_STUDIO_RPC_PERF_DIR", ZMK_WORKSPACE / "zmk-feature-studio-rpc-perf")
).resolve()

OVERLAYS = SKILL_DIR / "overlays"
RENODE_TEST_MODULE = SKILL_DIR / "renode-test-module"

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

ROLE_CONFIG = {
    "single": {
        "build_dir_name": "renode_single",
        "overlay": OVERLAYS / "studio-rpc-uart.overlay",
        "cmake_args": [
            "-DCONFIG_ZMK_STUDIO=y",
            "-DCONFIG_ZMK_STUDIO_RPC_PERF_HANDLER=y",
            "-DCONFIG_ZMK_STUDIO_TRANSPORT_UART=n",
            "-DCONFIG_ZMK_RENODE_STUDIO_UART_TRANSPORT=y",
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


def build(role: str, pristine: bool = False, quiet: bool = False) -> Path:
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

    if not quiet:
        print("running:", " ".join(cmd), file=sys.stderr)

    result = subprocess.run(cmd, cwd=WEST_TOPDIR, env=build_env(), capture_output=quiet, text=True)
    if result.returncode != 0:
        if quiet:
            sys.stderr.write(result.stdout or "")
            sys.stderr.write(result.stderr or "")
        raise SystemExit(f"west build failed for role={role} (exit {result.returncode})")

    elf = build_dir / "zephyr" / "zmk.elf"
    if not elf.exists():
        raise SystemExit(f"build reported success but {elf} is missing")
    return elf


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--role", required=True, choices=sorted(ROLE_CONFIG))
    ap.add_argument("--pristine", action="store_true", help="force a clean rebuild")
    ap.add_argument("--quiet", action="store_true", help="only print the resulting ELF path")
    args = ap.parse_args()

    elf = build(args.role, pristine=args.pristine, quiet=args.quiet)
    print(str(elf))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
