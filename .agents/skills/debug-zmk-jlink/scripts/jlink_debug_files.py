#!/usr/bin/env python3
"""Generate small J-Link/GDB helper files for a ZMK build directory."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


def find_gdb(build_info: Path) -> str:
    if build_info.exists():
        text = build_info.read_text(errors="replace")
        match = re.search(r"path: (/.+zephyr-sdk[^\n]+)", text)
        if match:
            sdk = Path(match.group(1).strip())
            candidate = sdk / "arm-zephyr-eabi/bin/arm-zephyr-eabi-gdb"
            if candidate.exists():
                return str(candidate)
    return "arm-zephyr-eabi-gdb"


def find_gdb_server() -> str:
    return shutil.which("JLinkGDBServerCLExe") or shutil.which("JLinkGDBServerExe") or "JLinkGDBServerCLExe"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--device", default="nRF52840_xxAA")
    parser.add_argument("--speed", default="4000")
    parser.add_argument("--gdb-port", default="2331")
    args = parser.parse_args()

    build_dir = args.build_dir.resolve()
    elf = build_dir / "zephyr/zmk.elf"
    hex_file = build_dir / "zephyr/zmk.hex"
    out_dir = build_dir / "jlink"
    out_dir.mkdir(parents=True, exist_ok=True)

    gdbinit = out_dir / "zmk-jlink.gdbinit"
    gdbinit.write_text(
        "\n".join(
            [
                "set confirm off",
                "set pagination off",
                f"target remote :{args.gdb_port}",
                "monitor halt",
                "monitor speed auto",
                "set print pretty on",
                "define zmk-freeze-capture",
                "  monitor halt",
                "  info registers",
                "  bt",
                "  thread apply all bt",
                "  info symbol $pc",
                "end",
                "define zmk-break-studio",
                "  b k_panic",
                "  b z_fatal_error",
                "  b z_check_thread_stack_fail",
                "  b studio_framing_process_byte",
                "  b zmk_rpc_get_rx_buf",
                "  b zmk_rpc_get_tx_buf",
                "  b zmk_studio_core_lock",
                "  b zmk_studio_core_unlock",
                "end",
                "",
            ]
        )
    )

    commander = out_dir / "flash-and-run.jlink"
    commander.write_text(
        "\n".join(
            [
                f"device {args.device}",
                "if SWD",
                f"speed {args.speed}",
                "r",
                "h",
                f"loadfile {hex_file}",
                "r",
                "g",
                "qc",
                "",
            ]
        )
    )

    server = out_dir / "start-gdb-server.sh"
    server.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"{find_gdb_server()} -device {args.device} -if SWD -speed {args.speed} "
        f"-port {args.gdb_port} -swoport 2332 -telnetport 2333\n"
    )
    server.chmod(0o755)

    gdb = find_gdb(build_dir / "build_info.yml")
    print(f"Wrote {gdbinit}")
    print(f"Wrote {commander}")
    print(f"Wrote {server}")
    print()
    print("Start server:")
    print(f"  {server}")
    print("Connect GDB:")
    print(f"  {gdb} {elf} -x {gdbinit}")
    print("Flash with JLinkExe:")
    print(f"  JLinkExe -CommandFile {commander}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
