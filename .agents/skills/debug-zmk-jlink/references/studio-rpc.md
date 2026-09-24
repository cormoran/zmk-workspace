# ZMK Studio RPC Notes

Use this reference after reading the repo's `docs/zmk-studio-rpc.md` or the upstream ZMK `docs/docs/development/studio-rpc-protocol.md`.

## Framing

Studio RPC uses protobuf payloads framed on the transport:

- Start of frame: `0xAB`
- Escape byte: `0xAC`
- End of frame: `0xAD`
- Any payload byte equal to `0xAB`, `0xAC`, or `0xAD` is escaped by prefixing `0xAC`; the byte value itself is unchanged.

USB Studio transport is CDC/ACM UART. BLE transport uses the Studio service `00000000-0196-6107-c967-c5cfb1c2482a` and characteristic `00000001-0196-6107-c967-c5cfb1c2482a`.

## Proto Loading

Local ZMK checkouts usually include the Studio messages at:

```text
dependencies/modules/msgs/zmk-studio-messages/proto/zmk
```

Important files:

- `studio.proto`: top-level `Request`, `Response`, `RequestResponse`, `Notification`.
- `core.proto`: `get_device_info`, `get_lock_state`, `lock`, `reset_settings`.
- `custom.proto`: `list_custom_subsystems` and `call`.
- Feature modules may provide additional custom payload protos; inspect each module's `proto/` and `src/studio/*handler*.c`.

## Low-Risk Probe Sequence

Use this order before sending custom payloads:

1. `core.get_device_info`
2. `core.get_lock_state`
3. `custom.list_custom_subsystems`
4. If `cormoran__devtool` is present, call `devtool get-lock-state`; call `devtool unlock` only when secured requests need it.
5. Read passive notifications for a few seconds while pressing the Studio unlock key or changing state.
6. Repeat benign read requests in a loop while collecting logs.

If `list_custom_subsystems` succeeds, record `index`, `identifier`, and `ui_url`. Do not assume indexes are stable across builds or resets.

The Abyss Tester XIAO sample used while creating this skill expected these custom identifiers:

```text
cormoran__devtool
cormoran__physical_layouts
cormoran_custom_settings
cormoran_rip
cormoran__runtime_combo
cormoran__runtime_macro
```

Treat this list as sample-specific. For other keyboards, use `custom-list` output as the source of truth.

## Workspace CLI

When `tools/zmk-studio-rpc` exists, use it before writing ad hoc protobuf code:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc --workspace "$ZMK_WORKSPACE" list-ports
PYTHONPATH=tools tools/zmk-studio-rpc --workspace "$ZMK_WORKSPACE" --port "$PORT" probe
PYTHONPATH=tools tools/zmk-studio-rpc --workspace "$ZMK_WORKSPACE" --port "$PORT" custom-list
```

For a module-owned custom subsystem:

```bash
PYTHONPATH=tools tools/zmk-studio-rpc \
  --workspace "$ZMK_WORKSPACE" \
  --port "$PORT" \
  custom-call \
  --identifier "$CUSTOM_SUBSYSTEM_ID" \
  --proto "$CUSTOM_PROTO" \
  --request-type "$REQUEST_TYPE" \
  --response-type "$RESPONSE_TYPE" \
  --json "$REQUEST_JSON"
```

Use `--transport pyusb` when the device is visible via USB but no usable CDC ACM node is available to the process. Use `--transport ble --ble-address "$ADDR"` only when the firmware enables BLE Studio transport.

## Payload Safety

Keep custom payload length under `CONFIG_ZMK_STUDIO_RPC_CUSTOM_SUBSYSTEM_REQUEST_PAYLOAD_MAX_BYTES`. Also compare total response size with `CONFIG_ZMK_STUDIO_RPC_TX_BUF_SIZE`.

Before sending a custom call:

- Locate the subsystem identifier in the build map or startup log.
- Read the handler C file to identify expected request type, permissions, lock-state behavior, and error responses.
- Generate or hand-encode the feature-specific protobuf payload from the matching module proto.
- Start with read-only/get/list requests.
- Check payload sizes against both the custom subsystem payload max and the Studio TX/RX buffer sizes from `.config`.

## Freeze Correlation

For each RPC experiment, log:

- Wall-clock time and request id.
- Request type and payload length.
- Response, notification, timeout, framing error, or serial disconnect.
- J-Link state if attached: running, halted PC, fault, reset.
- Serial/RTT log lines around the request.

If the firmware freezes after a request timeout, halt with J-Link before power-cycling. The halted PC and current thread are often more useful than logs after reset.
