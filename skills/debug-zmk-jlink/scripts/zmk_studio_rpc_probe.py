#!/usr/bin/env python3
"""Probe ZMK Studio RPC over a serial CDC/ACM port."""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from google.protobuf.json_format import MessageToJson


SOF = 0xAB
ESC = 0xAC
EOF = 0xAD
SPECIAL = {SOF, ESC, EOF}


def frame(payload: bytes) -> bytes:
    out = bytearray([SOF])
    for byte in payload:
        if byte in SPECIAL:
            out.append(ESC)
        out.append(byte)
    out.append(EOF)
    return bytes(out)


def read_frame(port: serial.Serial, timeout: float) -> bytes | None:
    deadline = time.monotonic() + timeout
    in_frame = False
    escaped = False
    payload = bytearray()
    while time.monotonic() < deadline:
        chunk = port.read(1)
        if not chunk:
            continue
        byte = chunk[0]
        if not in_frame:
            if byte == SOF:
                in_frame = True
                payload.clear()
            continue
        if escaped:
            payload.append(byte)
            escaped = False
        elif byte == ESC:
            escaped = True
        elif byte == EOF:
            return bytes(payload)
        elif byte == SOF:
            payload.clear()
        else:
            payload.append(byte)
    return None


def compile_protos(proto_dir: Path, out_dir: Path) -> None:
    proto_files = sorted(proto_dir.glob("*.proto"))
    if not proto_files:
        raise SystemExit(f"No .proto files found in {proto_dir}")
    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{proto_dir}",
        f"--python_out={out_dir}",
        *[str(path) for path in proto_files],
    ]
    subprocess.run(cmd, check=True)


def load_modules(proto_dir: Path):
    temp = tempfile.TemporaryDirectory(prefix="zmk-studio-proto-")
    out_dir = Path(temp.name)
    compile_protos(proto_dir, out_dir)
    sys.path.insert(0, str(out_dir))
    modules = {
        "studio": importlib.import_module("studio_pb2"),
        "core": importlib.import_module("core_pb2"),
        "custom": importlib.import_module("custom_pb2"),
    }
    return temp, modules


def print_response(studio_pb2, payload: bytes) -> None:
    response = studio_pb2.Response()
    response.ParseFromString(payload)
    print(MessageToJson(response, preserving_proto_field_name=True, indent=2))


def request_core(studio_pb2, request_id: int, field: str):
    req = studio_pb2.Request()
    req.request_id = request_id
    setattr(req.core, field, True)
    return req


def request_list_custom(studio_pb2, request_id: int):
    req = studio_pb2.Request()
    req.request_id = request_id
    req.custom.list_custom_subsystems.SetInParent()
    return req


def request_custom_call(studio_pb2, request_id: int, subsystem_index: int, payload: bytes):
    req = studio_pb2.Request()
    req.request_id = request_id
    req.custom.call.subsystem_index = subsystem_index
    req.custom.call.payload = payload
    return req


def send_and_print(ser: serial.Serial, studio_pb2, req, timeout: float) -> None:
    print(f"> request_id={req.request_id} {req.WhichOneof('subsystem')}")
    ser.write(frame(req.SerializeToString()))
    ser.flush()
    payload = read_frame(ser, timeout)
    if payload is None:
        print("! timeout waiting for response")
        return
    print_response(studio_pb2, payload)


def print_dry_run(req) -> None:
    payload = req.SerializeToString()
    encoded = frame(payload)
    print(f"> request_id={req.request_id} {req.WhichOneof('subsystem')}")
    print(f"  payload_hex={payload.hex()}")
    print(f"  framed_hex={encoded.hex()}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/ttyACM0")
    parser.add_argument("--proto-dir", required=True, type=Path, help="Directory containing studio.proto")
    parser.add_argument("--baud", default=115200, type=int)
    parser.add_argument("--timeout", default=2.0, type=float)
    parser.add_argument("--device-info", action="store_true")
    parser.add_argument("--lock-state", action="store_true")
    parser.add_argument("--lock", action="store_true")
    parser.add_argument("--reset-settings", action="store_true")
    parser.add_argument("--list-custom", action="store_true")
    parser.add_argument("--custom-call-index", type=int)
    parser.add_argument("--custom-call-payload-hex", default="")
    parser.add_argument("--repeat", default=1, type=int)
    parser.add_argument("--delay", default=0.1, type=float)
    parser.add_argument("--read-notifications", default=0.0, type=float, metavar="SECONDS")
    parser.add_argument("--request-id", default=1, type=int)
    parser.add_argument("--dry-run", action="store_true", help="Build requests and print framed hex without opening the port")
    args = parser.parse_args()

    proto_temp, modules = load_modules(args.proto_dir.resolve())
    studio_pb2 = modules["studio"]

    requests = []
    request_id = args.request_id
    for _ in range(args.repeat):
        if args.device_info:
            requests.append(request_core(studio_pb2, request_id, "get_device_info"))
            request_id += 1
        if args.lock_state:
            requests.append(request_core(studio_pb2, request_id, "get_lock_state"))
            request_id += 1
        if args.lock:
            requests.append(request_core(studio_pb2, request_id, "lock"))
            request_id += 1
        if args.reset_settings:
            requests.append(request_core(studio_pb2, request_id, "reset_settings"))
            request_id += 1
        if args.list_custom:
            requests.append(request_list_custom(studio_pb2, request_id))
            request_id += 1
        if args.custom_call_index is not None:
            payload = bytes.fromhex(args.custom_call_payload_hex)
            requests.append(request_custom_call(studio_pb2, request_id, args.custom_call_index, payload))
            request_id += 1

    if args.dry_run:
        for req in requests:
            print_dry_run(req)
        return 0

    try:
        import serial

        with serial.Serial(args.port, args.baud, timeout=0.05) as ser:
            ser.reset_input_buffer()
            for req in requests:
                send_and_print(ser, studio_pb2, req, args.timeout)
                time.sleep(args.delay)
            if args.read_notifications:
                deadline = time.monotonic() + args.read_notifications
                print(f"> reading notifications for {args.read_notifications:.1f}s")
                while time.monotonic() < deadline:
                    payload = read_frame(ser, min(args.timeout, max(0.1, deadline - time.monotonic())))
                    if payload:
                        print_response(studio_pb2, payload)
    finally:
        proto_temp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
