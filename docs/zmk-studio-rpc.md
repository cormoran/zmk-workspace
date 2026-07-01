# ZMK Studio RPC Python tools

This workspace includes a small Python library and CLI for debugging ZMK keyboards over ZMK
Studio RPC.

The code lives in `tools/zmk_studio_rpc/`. Run it from the repository root with:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc --workspace "$ZMK_WORKSPACE" list-ports
```

## Concepts

- Studio RPC messages are protobuf payloads wrapped in ZMK's `0xAB` / `0xAC` / `0xAD` framing.
- Official RPC methods are available through `StudioClient`, for example `get_device_info()`,
  `get_lock_state()`, `get_keymap()`, and `list_custom_subsystems()`.
- Custom subsystems are optional. `list_custom_subsystems()` returns an empty list when the
  firmware does not support the custom extension, and `custom_subsystem(identifier, required=False)`
  returns `None` when an identifier is absent.
- Custom subsystem indices are device/runtime specific. Always resolve an identifier with
  `list_custom_subsystems()` instead of hard-coding an index.
- Custom subsystem payloads use the module's own proto. Pass that proto to `ProtoBundle` or the CLI
  before making the call.

BLE transport is implemented as an optional transport and requires the `bleak` Python package. USB
serial transport only needs `pyserial`.

There is also a `pyusb` USB CDC transport for sandboxed hosts where Linux has a CDC ACM interface
but no usable `/dev/ttyACM*` node is visible to the process. It talks to the CDC bulk endpoints
directly and may need permission to detach the kernel driver from the selected CDC interface.

## CLI examples

Official RPC:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --port "$PORT" \
  info

PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --port "$PORT" \
  lock-state
```

List custom subsystems when the firmware supports a custom Studio RPC extension:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --port "$PORT" \
  custom-list
```

Probe both official and safe custom paths:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --port "$PORT" \
  probe
```

When the device appears in `lsusb` but no usable tty exists, probe a CDC data interface directly:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --transport pyusb \
  --usb-data-interface "$USB_DATA_INTERFACE" \
  probe
```

If the device exposes multiple CDC ACM functions, select the data interface that belongs to the
Studio RPC endpoint. `lsusb -v`, the Zephyr USB descriptors, or sysfs can be used to identify the
matching CDC data interface.

Call a custom proto directly:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --port "$PORT" \
  custom-call \
  --identifier "$CUSTOM_SUBSYSTEM_ID" \
  --proto "$CUSTOM_PROTO" \
  --request-type "$CUSTOM_REQUEST_TYPE" \
  --response-type "$CUSTOM_RESPONSE_TYPE" \
  --json "$CUSTOM_REQUEST_JSON"
```

Devtool convenience calls are available for firmware that includes the matching devtool custom
subsystem and proto:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --port "$PORT" \
  devtool get-lock-state

PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --port "$PORT" \
  devtool unlock
```

## Library examples

Official RPC:

```python
from zmk_studio_rpc import ProtoBundle, SerialTransport, StudioClient

protos = ProtoBundle.from_workspace("path/to/zmk/workspace")
transport = SerialTransport("path/to/serial-port")

with StudioClient(transport, protos) as client:
    info = client.get_device_info()
    print(info.name, bytes(info.serial_number).hex())
    print(protos.core.LockState.Name(client.get_lock_state()))
```

Custom subsystem RPC:

```python
from google.protobuf import json_format
from zmk_studio_rpc import ProtoBundle, SerialTransport, StudioClient

workspace = "path/to/zmk/workspace"
custom_proto = "path/to/custom/subsystem.proto"
protos = ProtoBundle.from_workspace(workspace, custom_proto_files=[custom_proto])

Request = protos.message_class("custom.package.Request")
Response = protos.message_class("custom.package.Response")

with StudioClient(SerialTransport("path/to/serial-port"), protos) as client:
    service = client.custom_subsystem("custom_subsystem_identifier", required=False)
    if service is None:
        print("custom subsystem is not present on this firmware")
    else:
        request = Request()
        json_format.Parse('{"exampleField": {}}', request)
        response = service.call(request, Response)
        print(response)
```

## Hardware validation checklist

Build and flash the same firmware configuration that users will run on the keyboard. The exact
command depends on the board, shield, runner, and local toolchain setup. For a typical ZMK workspace,
the build step looks like:

```bash
cd "$ZMK_WORKSPACE"
west zmk-build -d ./build -q
```

Then flash the produced artifact with the runner that matches the board and debug probe:

```bash
west flash -d ./build
```

If the board uses a bootloader layout and is flashed over SWD, make sure execution starts at the
application image expected by that bootloader. Some workflows reset into the bootloader first; others
can start the application directly through the board runner or debugger.

After the keyboard enumerates over USB or BLE, validate the official RPC path first:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --port "$PORT" \
  info

PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --port "$PORT" \
  lock-state
```

For firmware that includes a custom subsystem, validate that the subsystem is discoverable before
calling it:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --port "$PORT" \
  custom-list
```

Then call the subsystem with its own proto and message types:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --port "$PORT" \
  custom-call \
  --identifier "$CUSTOM_SUBSYSTEM_ID" \
  --proto "$CUSTOM_PROTO" \
  --request-type "$CUSTOM_REQUEST_TYPE" \
  --response-type "$CUSTOM_RESPONSE_TYPE" \
  --json "$CUSTOM_REQUEST_JSON"
```

For a quick smoke test that tolerates absent custom subsystem support, use `probe`:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --port "$PORT" \
  probe
```
