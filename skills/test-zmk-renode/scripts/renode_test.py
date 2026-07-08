#!/usr/bin/env python3
"""Renode-based tests for ZMK on the XIAO nRF52840 (Studio RPC + split).

Runnable directly:
    python renode_test.py
    python renode_test.py -v RenodeZmkTests.test_t1_studio_rpc_uart

Or via unittest discovery:
    python -m unittest renode_test -v

Tiers (see ../SKILL.md for the full writeup):
    T0 - boot a single board, see the ZMK banner on the console UART.
    T1 - Studio RPC over UART (the Renode stand-in for USB) round-trips a
         real protobuf request/response. MUST PASS.
    T2 - wired split: two machines, central receives a peripheral-originated
         key event over the split-wired UART link.
    T3 - BLE (experimental). Renode's nRF52840 radio itself works (it's used
         by Renode's own bundled Zephyr BLE examples), but ZMK's BLE stack
         hits a settings/controller-command-timeout kernel oops around 10s
         after boot on this platform+Zephyr version combination, before any
         peer is even involved. Gated off by default (see
         RENODE_ZMK_RUN_T3=1 to attempt it anyway) and documented in
         references/renode-notes.md / EXPERIMENT_LOG.md.

Auto-installs Renode (via install_renode.sh) if not already present. Exits
non-zero on any test failure (standard unittest behavior).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent

sys.path.insert(0, str(SCRIPTS_DIR))
import build_fw  # noqa: E402
import renode_harness  # noqa: E402
from renode_harness import (  # noqa: E402
    MonitorConnection,
    RenodeSession,
    RpcSocket,
    drain_text,
    find_or_install_renode as _find_or_install_renode,
    wait_for_text,
)

RENODE_VERSION = renode_harness.RENODE_VERSION_DEFAULT


# --------------------------------------------------------------------------
# Renode install discovery / bootstrap (thin wrapper: this skill always
# installs to the default RENODE_ROOT/<version> layout and always has
# install_renode.sh right next to it).
# --------------------------------------------------------------------------


def find_or_install_renode() -> str | None:
    return _find_or_install_renode(SCRIPTS_DIR / "install_renode.sh", RENODE_VERSION)


# --------------------------------------------------------------------------
# Protobuf message helpers (compile zmk-studio-messages protos on the fly)
# --------------------------------------------------------------------------


def load_studio_pb2():
    proto_dir = renode_harness.find_studio_proto_dir(build_fw.WEST_TOPDIR)
    try:
        return renode_harness.load_studio_pb2(proto_dir)
    except (FileNotFoundError, RuntimeError) as err:
        raise unittest.SkipTest(str(err))


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


class RenodeZmkTests(unittest.TestCase):
    renode_path: str | None = None

    @classmethod
    def setUpClass(cls):
        cls.renode_path = find_or_install_renode()
        if cls.renode_path is None:
            raise unittest.SkipTest("Renode is not installed and could not be auto-installed")

    def _alloc_port_base(self) -> int:
        """Pick a pseudo-random high port range per test. Using a fixed port
        per test previously caused a nasty failure mode: a Renode process
        left running by an earlier *failed* test run (e.g. because
        connect_uart() raised before addCleanup(session.stop) was
        registered) keeps holding the old port, so a later run's client
        silently connects to the *stale* process's monitor instead of its
        own fresh one -- the stale process never created the expected UART
        sockets, so every connect_uart() call then times out with
        "Connection refused" no matter how long you wait. Randomizing the
        base port each run sidesteps stale listeners; addCleanup below is
        also now registered immediately after start() so a live process
        doesn't leak in the first place."""
        import random

        return random.randint(26000, 40000)

    def _boot_single(self, elf: Path) -> tuple[RenodeSession, RpcSocket, RpcSocket]:
        port_base = self._alloc_port_base()
        session = RenodeSession(
            self.renode_path,
            SKILL_DIR / "platforms" / "single.resc",
            monitor_port=port_base,
            variables={
                "bin": f"@{elf}",
                "console_port": port_base + 1,
                "rpc_port": port_base + 2,
            },
            cwd=SKILL_DIR,
        )
        session.start()
        self.addCleanup(session.stop)  # register before any connect_uart() can raise
        console = session.connect_uart(port_base + 1)
        self.addCleanup(console.close)
        rpc = session.connect_uart(port_base + 2)
        self.addCleanup(rpc.close)
        session.go()
        return session, console, rpc

    # -- T0 -----------------------------------------------------------

    def test_t0_boot_single(self):
        """Boot a single-board ELF and confirm the real ZMK boot banner
        appears on the console UART -- proves the platform description,
        ELF load, and CPU execution all work."""
        elf = build_fw.build("single", quiet=True)
        session, console_sock, rpc = self._boot_single(elf)

        banner = wait_for_text(console_sock._sock, "Welcome to ZMK", timeout=15)
        self.assertIn(
            "Welcome to ZMK",
            banner,
            f"never saw ZMK boot banner on console UART; got:\n{banner}",
        )
        self.assertIn("*** Booting Zephyr OS build", banner)

    # -- T1 (must pass) -------------------------------------------------

    def test_t1_studio_rpc_uart(self):
        """Studio RPC over UART (the Renode stand-in for USB): send a real
        GetDeviceInfo request and assert a well-formed, correctly-decoded
        Response comes back with the configured keyboard name. Also sends a
        second request over the same connection to catch a regression of
        the TX-IRQ-storm bug (see renode-test-module's
        src/renode_uart_transport.c) where only the first RPC ever got a
        response."""
        studio_pb2 = load_studio_pb2()

        elf = build_fw.build("single", quiet=True)
        session, console_sock, rpc = self._boot_single(elf)

        # Let the console settle so we're not racing the boot banner.
        wait_for_text(console_sock._sock, "Welcome to ZMK", timeout=15)

        for i in range(2):
            req = studio_pb2.Request()
            req.request_id = i + 1
            req.core.get_device_info = True
            rpc.send(req.SerializeToString())
            resp_bytes = rpc.read_frame(timeout=10.0)
            self.assertIsNotNone(
                resp_bytes, f"request #{i + 1}: no RPC response frame received (timeout)"
            )
            resp = studio_pb2.Response()
            resp.ParseFromString(resp_bytes)
            self.assertEqual(resp.WhichOneof("type"), "request_response")
            self.assertEqual(resp.request_response.request_id, i + 1)
            self.assertEqual(resp.request_response.WhichOneof("subsystem"), "core")
            self.assertEqual(
                resp.request_response.core.get_device_info.name,
                "MAK",
                "GetDeviceInfoResponse.name did not match the configured keyboard name",
            )

    # -- T2 ---------------------------------------------------------------

    def test_t2_split_wired(self):
        """Two machines (central + peripheral), split-wired UARTs
        cross-connected via a Renode UART hub. Injects a synthetic GPIO
        keypress on the peripheral (well after boot, to avoid a startup
        race -- see references/renode-notes.md) and asserts the central
        receives and processes the relayed key position event."""
        central_elf = build_fw.build("central", quiet=True)
        peripheral_elf = build_fw.build("peripheral", quiet=True)

        port_base = self._alloc_port_base()
        session = RenodeSession(
            self.renode_path,
            SKILL_DIR / "platforms" / "split_wired.resc",
            monitor_port=port_base,
            variables={
                "central_bin": f"@{central_elf}",
                "peripheral_bin": f"@{peripheral_elf}",
                "central_console_port": port_base + 1,
                "peripheral_console_port": port_base + 2,
            },
            cwd=SKILL_DIR,
        )
        session.start()
        self.addCleanup(session.stop)  # register before any connect_uart() can raise
        central_console = session.connect_uart(port_base + 1)
        self.addCleanup(central_console.close)
        peripheral_console = session.connect_uart(port_base + 2)
        self.addCleanup(peripheral_console.close)
        session.go()

        wait_for_text(central_console._sock, "Welcome to ZMK", timeout=15)
        wait_for_text(peripheral_console._sock, "Welcome to ZMK", timeout=15)

        # Let both sides fully settle (uart_irq_rx_enable() on both ends,
        # kscan init, etc.) before generating a "real" event -- synthetic
        # kscan events fired in the first few ms of boot can race the
        # central's RX-enable and get silently dropped.
        time.sleep(3)
        drain_text(central_console._sock, timeout=0.2)  # discard anything already buffered

        assert session.mon is not None
        session.mon.execute('mach set "peripheral"')
        session.mon.execute("sysbus.gpio0 OnGPIO 2 true")
        time.sleep(0.3)
        session.mon.execute("sysbus.gpio0 OnGPIO 2 false")

        central_log = wait_for_text(central_console._sock, "position: 0", timeout=10)
        self.assertIn(
            "position: 0",
            central_log,
            "central never logged a position event relayed from the peripheral; "
            f"got:\n{central_log}",
        )

    # -- T3 (experimental, capped) ---------------------------------------

    @unittest.skipUnless(
        os.environ.get("RENODE_ZMK_RUN_T3") == "1",
        "T3 (BLE) is experimental and gated off by default -- ZMK's BLE stack hits a "
        "settings/HCI-command-timeout kernel oops ~10s after boot on this platform under "
        "Renode, before any peer is even involved (see references/renode-notes.md). Set "
        "RENODE_ZMK_RUN_T3=1 to reproduce.",
    )
    def test_t3_ble_single_board_boot(self):
        """Documents exactly where BLE breaks: even a single board with
        CONFIG_ZMK_BLE=y (no peer, no split, no Renode BLE medium wiring at
        all) fails during boot. Not a real BLE/split-over-BLE test -- see
        the class docstring and references/renode-notes.md."""
        import tempfile

        overlay = SKILL_DIR / "overlays" / "studio-rpc-uart.overlay"
        build_dir = build_fw.WEST_TOPDIR / "build" / "renode_t3_ble_probe"
        cmd = [
            "west",
            "build",
            "-s",
            str(build_fw.WEST_TOPDIR / "dependencies" / "zmk" / "app"),
            "-d",
            str(build_dir),
            "-b",
            build_fw.BOARD,
            "-p",
            "auto",
            "--",
            f"-DSHIELD={build_fw.SHIELD}",
            f"-DZMK_CONFIG={build_fw.WEST_TOPDIR / 'tests' / 'zmk-config' / 'config'}",
            "-DZMK_EXTRA_MODULES="
            + ";".join(
                str(p)
                for p in (
                    build_fw.WEST_TOPDIR / "tests" / "zmk-config",
                    build_fw.WEST_TOPDIR,
                )
            ),
            f"-DEXTRA_DTC_OVERLAY_FILE={overlay}",
            "-DCONFIG_ZMK_STUDIO=y",
            *build_fw.COMMON_ARGS,  # USB off, board CDC-ACM cascade off, console/log on uart0
            # Last -D wins on the cmake command line: this must come *after*
            # COMMON_ARGS, which sets CONFIG_ZMK_BLE=n for the other tiers.
            "-DCONFIG_ZMK_BLE=y",
        ]
        result = subprocess.run(cmd, cwd=build_fw.WEST_TOPDIR, env=build_fw.build_env(), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        elf = build_dir / "zephyr" / "zmk.elf"

        session, console_sock, _rpc = self._boot_single(elf)
        log = wait_for_text(console_sock._sock, "ZEPHYR FATAL ERROR", timeout=20)
        # We *expect* the fatal error today; this test documents the
        # failure mode rather than asserting BLE works.
        self.assertIn("ZEPHYR FATAL ERROR", log, f"expected known BLE failure did not occur; got:\n{log}")


if __name__ == "__main__":
    unittest.main()
