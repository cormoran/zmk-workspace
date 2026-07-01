#!/usr/bin/env python3
"""Summarize ZMK build artifacts relevant to Studio RPC and J-Link debugging."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path


KEY_CONFIGS = [
    "CONFIG_ZMK_STUDIO",
    "CONFIG_ZMK_STUDIO_LOCKING",
    "CONFIG_ZMK_STUDIO_TRANSPORT_UART",
    "CONFIG_ZMK_STUDIO_TRANSPORT_BLE",
    "CONFIG_ZMK_STUDIO_RPC_THREAD_STACK_SIZE",
    "CONFIG_ZMK_STUDIO_RPC_RX_BUF_SIZE",
    "CONFIG_ZMK_STUDIO_RPC_TX_BUF_SIZE",
    "CONFIG_ZMK_STUDIO_RPC_CUSTOM_SUBSYSTEM_REQUEST_PAYLOAD_MAX_BYTES",
    "CONFIG_ZMK_DEVTOOL",
    "CONFIG_ZMK_PHYSICAL_LAYOUTS_STUDIO_RPC",
    "CONFIG_ZMK_CUSTOM_SETTINGS_STUDIO_RPC",
    "CONFIG_ZMK_RUNTIME_COMBO_STUDIO_RPC",
    "CONFIG_ZMK_RUNTIME_MACRO_STUDIO_RPC",
    "CONFIG_MAIN_STACK_SIZE",
    "CONFIG_ISR_STACK_SIZE",
    "CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE",
    "CONFIG_INPUT_THREAD_STACK_SIZE",
    "CONFIG_ZMK_LOW_PRIORITY_THREAD_STACK_SIZE",
    "CONFIG_USB_WORKQUEUE_STACK_SIZE",
    "CONFIG_USB_NRFX_WORK_QUEUE_STACK_SIZE",
    "CONFIG_ASSERT",
    "CONFIG_INIT_STACKS",
    "CONFIG_HW_STACK_PROTECTION",
    "CONFIG_THREAD_STACK_INFO",
    "CONFIG_THREAD_MONITOR",
    "CONFIG_THREAD_NAME",
    "CONFIG_THREAD_ANALYZER",
    "CONFIG_STACK_USAGE",
    "CONFIG_DEBUG_THREAD_INFO",
    "CONFIG_DEBUG_INFO",
    "CONFIG_DEBUG_OPTIMIZATIONS",
    "CONFIG_NO_OPTIMIZATIONS",
    "CONFIG_LOG",
    "CONFIG_LOG_OUTPUT",
    "CONFIG_LOG_MODE_IMMEDIATE",
    "CONFIG_USE_SEGGER_RTT",
    "CONFIG_LOG_BACKEND_RTT",
    "CONFIG_SHELL",
]

TOOLS = [
    "JLinkExe",
    "JLinkGDBServerCLExe",
    "JLinkGDBServerExe",
    "JLinkRTTClient",
    "JLinkRTTLogger",
    "arm-zephyr-eabi-gdb",
    "arm-zephyr-eabi-nm",
    "gdb-multiarch",
    "protoc",
    "python3",
]


def read_config(config_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not config_path.exists():
        return values
    for line in config_path.read_text(errors="replace").splitlines():
        if line.startswith("# CONFIG_") and " is not set" in line:
            key = line.split()[1]
            values[key] = "not set"
        elif line.startswith("CONFIG_") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def print_file_status(build_dir: Path) -> None:
    print("Artifacts")
    for rel in [
        "build_info.yml",
        "stdout_and_stderr.log",
        "zephyr/.config",
        "zephyr/zmk.elf",
        "zephyr/zmk.map",
        "zephyr/zmk.uf2",
        "zephyr/zmk.hex",
    ]:
        path = build_dir / rel
        status = "ok" if path.exists() else "missing"
        size = f" {path.stat().st_size} bytes" if path.exists() else ""
        print(f"  {rel}: {status}{size}")


def print_build_identity(build_dir: Path) -> None:
    info = build_dir / "build_info.yml"
    if not info.exists():
        return
    print("\nBuild identity")
    patterns = [
        r"^\s+name: .+",
        r"^\s+version: .+",
        r"^\s+zephyr-base: .+",
        r"^\s+path: /.+zephyr-sdk.+",
        r"^\s+command: .+",
        r"^\s+topdir: .+",
        r"^\s+svdfile: .+",
    ]
    wanted = re.compile("|".join(f"(?:{p})" for p in patterns))
    for line in info.read_text(errors="replace").splitlines():
        if wanted.search(line):
            print(f"  {line.strip()}")


def print_configs(build_dir: Path) -> None:
    values = read_config(build_dir / "zephyr/.config")
    print("\nKey Kconfig")
    for key in KEY_CONFIGS:
        print(f"  {key}={values.get(key, 'missing')}")


def print_memory_and_warnings(build_dir: Path) -> None:
    log = build_dir / "stdout_and_stderr.log"
    if not log.exists():
        return
    lines = log.read_text(errors="replace").splitlines()
    print("\nMemory summary")
    for line in lines:
        if re.search(r"\b(FLASH|RAM|IDT_LIST):", line) or "Memory region" in line:
            print(f"  {line}")
    print("\nWarnings/errors")
    matches = [line for line in lines if re.search(r"\b(warning|error|fault|stack|overflow)\b", line, re.I)]
    for line in matches[-80:]:
        print(f"  {line}")
    if not matches:
        print("  none found in build log")


def print_map_hints(build_dir: Path) -> None:
    map_path = build_dir / "zephyr/zmk.map"
    if not map_path.exists():
        return
    print("\nMap hints")
    needles = [
        "studio_rpc_thread",
        "zmk_rpc_get_rx_buf",
        "zmk_rpc_get_tx_buf",
        "studio_framing_process_byte",
        "_zmk_rpc_custom_subsystem_list_start",
        "_zmk_rpc_custom_subsystem_list_end",
        "z_check_thread_stack_fail",
    ]
    lines = map_path.read_text(errors="replace").splitlines()
    for needle in needles:
        for line in lines:
            if needle in line:
                print(f"  {line.strip()}")
                break


def print_tools() -> None:
    print("\nHost tools")
    for tool in TOOLS:
        print(f"  {tool}: {shutil.which(tool) or 'missing'}")
    print("\nUSB probes")
    lsusb = shutil.which("lsusb")
    if not lsusb:
        print("  lsusb: missing")
        return
    try:
        result = subprocess.run([lsusb], check=False, capture_output=True, text=True, timeout=5)
    except Exception as exc:
        print(f"  lsusb failed: {exc}")
        return
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        print(f"  lsusb failed: {detail or f'exit {result.returncode}'}")
        return
    matches = [line for line in result.stdout.splitlines() if re.search(r"SEGGER|J-Link", line, re.I)]
    if matches:
        for line in matches:
            print(f"  {line}")
    else:
        print("  no SEGGER/J-Link USB device found")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", required=True, type=Path)
    args = parser.parse_args()
    build_dir = args.build_dir.resolve()
    print(f"Build dir: {build_dir}")
    print_file_status(build_dir)
    print_build_identity(build_dir)
    print_configs(build_dir)
    print_memory_and_warnings(build_dir)
    print_map_hints(build_dir)
    print_tools()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
