"""High level ZMK Studio RPC client."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any

from google.protobuf.message import Message

from .proto import ProtoBundle
from .transport import Transport


class StudioRPCError(RuntimeError):
    pass


class StudioRPCMetaError(StudioRPCError):
    def __init__(self, code: int, name: str) -> None:
        super().__init__(f"Studio RPC meta error: {name} ({code})")
        self.code = code
        self.name = name


class SubsystemNotFoundError(StudioRPCError):
    pass


@dataclass(frozen=True)
class CustomSubsystemInfo:
    index: int
    identifier: str
    ui_urls: tuple[str, ...] = ()


class StudioClient:
    def __init__(
        self,
        transport: Transport,
        protos: ProtoBundle,
        *,
        response_timeout: float = 5.0,
    ) -> None:
        self.transport = transport
        self.protos = protos
        self.response_timeout = response_timeout
        self._request_ids = itertools.count(1)
        self.notifications: list[Message] = []

    def __enter__(self) -> "StudioClient":
        self.open()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def open(self) -> None:
        self.transport.open()

    def close(self) -> None:
        self.transport.close()

    def request(self, subsystem_name: str, subsystem_request: Message) -> Message:
        request_id = next(self._request_ids)
        request = self.protos.studio.Request(request_id=request_id)
        getattr(request, subsystem_name).CopyFrom(subsystem_request)
        self.transport.write_frame(request.SerializeToString())

        while True:
            payload = self.transport.read_frame(timeout=self.response_timeout)
            response = self.protos.studio.Response()
            response.ParseFromString(payload)
            response_type = response.WhichOneof("type")

            if response_type == "notification":
                self.notifications.append(response.notification)
                continue

            if response_type != "request_response":
                continue

            request_response = response.request_response
            if request_response.request_id != request_id:
                continue

            subsystem = request_response.WhichOneof("subsystem")
            if subsystem == "meta":
                self._raise_meta_error(request_response.meta)
                return request_response.meta
            if subsystem != subsystem_name:
                raise StudioRPCError(
                    f"Unexpected response subsystem {subsystem!r}; expected {subsystem_name!r}"
                )
            return getattr(request_response, subsystem)

    def get_device_info(self) -> Message:
        response = self.request("core", self.protos.core.Request(get_device_info=True))
        return response.get_device_info

    def get_lock_state(self) -> int:
        response = self.request("core", self.protos.core.Request(get_lock_state=True))
        return int(response.get_lock_state)

    def lock(self) -> bool:
        self.request("core", self.protos.core.Request(lock=True))
        return True

    def reset_settings(self) -> bool:
        response = self.request("core", self.protos.core.Request(reset_settings=True))
        return bool(response.reset_settings)

    def get_keymap(self) -> Message:
        response = self.request("keymap", self.protos.keymap.Request(get_keymap=True))
        return response.get_keymap

    def check_unsaved_changes(self) -> bool:
        response = self.request("keymap", self.protos.keymap.Request(check_unsaved_changes=True))
        return bool(response.check_unsaved_changes)

    def list_custom_subsystems(self) -> list[CustomSubsystemInfo]:
        try:
            response = self.request(
                "custom",
                self.protos.custom.Request(
                    list_custom_subsystems=self.protos.custom.ListCustomSubsystemRequest()
                ),
            )
        except StudioRPCMetaError as exc:
            if exc.name == "RPC_NOT_FOUND":
                return []
            raise
        if response.WhichOneof("response_type") != "list_custom_subsystems":
            return []

        return [
            CustomSubsystemInfo(
                index=int(subsystem.index),
                identifier=str(subsystem.identifier).rstrip("\x00"),
                ui_urls=tuple(str(url).rstrip("\x00") for url in subsystem.ui_url),
            )
            for subsystem in response.list_custom_subsystems.subsystems
        ]

    def find_custom_subsystem(self, identifier: str) -> CustomSubsystemInfo | None:
        for subsystem in self.list_custom_subsystems():
            if subsystem.identifier == identifier:
                return subsystem
        return None

    def require_custom_subsystem(self, identifier: str) -> CustomSubsystemInfo:
        subsystem = self.find_custom_subsystem(identifier)
        if subsystem is None:
            raise SubsystemNotFoundError(f"Custom subsystem not found: {identifier}")
        return subsystem

    def custom_subsystem(
        self,
        identifier: str,
        *,
        required: bool = True,
    ) -> "CustomSubsystemClient | None":
        subsystem = (
            self.require_custom_subsystem(identifier)
            if required
            else self.find_custom_subsystem(identifier)
        )
        if subsystem is None:
            return None
        return CustomSubsystemClient(self, subsystem)

    def custom_call_by_index(self, subsystem_index: int, payload: bytes) -> bytes:
        response = self.request(
            "custom",
            self.protos.custom.Request(
                call=self.protos.custom.CallRequest(
                    subsystem_index=subsystem_index,
                    payload=payload,
                )
            ),
        )
        if response.WhichOneof("response_type") != "call":
            raise StudioRPCError(f"Unexpected custom response: {response.WhichOneof('response_type')}")
        if int(response.call.subsystem_index) != int(subsystem_index):
            raise StudioRPCError(
                f"Custom response index mismatch: {response.call.subsystem_index} != {subsystem_index}"
            )
        return bytes(response.call.payload)

    def _raise_meta_error(self, response: Message) -> None:
        response_type = response.WhichOneof("response_type")
        if response_type == "no_response":
            return
        if response_type == "simple_error":
            code = int(response.simple_error)
            name = self.protos.meta.ErrorConditions.Name(code)
            raise StudioRPCMetaError(code, name)
        raise StudioRPCError(f"Unexpected meta response: {response_type}")


@dataclass
class CustomSubsystemClient:
    client: StudioClient
    subsystem: CustomSubsystemInfo

    def call(self, request: Message, response_cls: type[Message] | None = None) -> Message | bytes:
        payload = self.client.custom_call_by_index(
            self.subsystem.index,
            request.SerializeToString(),
        )
        if response_cls is None:
            return payload
        response = response_cls()
        response.ParseFromString(payload)
        return response
