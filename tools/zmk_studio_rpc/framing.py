"""ZMK Studio RPC byte framing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


SOF = 0xAB
ESC = 0xAC
EOF = 0xAD
SPECIAL_BYTES = {SOF, ESC, EOF}


def encode_frame(payload: bytes) -> bytes:
    framed = bytearray([SOF])
    for byte in payload:
        if byte in SPECIAL_BYTES:
            framed.append(ESC)
        framed.append(byte)
    framed.append(EOF)
    return bytes(framed)


@dataclass
class FrameDecoder:
    """Incremental decoder for the Studio RPC framing protocol."""

    in_frame: bool = False
    escaped: bool = False
    payload: bytearray = field(default_factory=bytearray)

    def reset(self) -> None:
        self.in_frame = False
        self.escaped = False
        self.payload.clear()

    def feed(self, data: bytes | Iterable[int]) -> list[bytes]:
        frames: list[bytes] = []
        for byte in data:
            frame = self.feed_byte(byte)
            if frame is not None:
                frames.append(frame)
        return frames

    def feed_byte(self, byte: int) -> bytes | None:
        byte &= 0xFF

        if not self.in_frame:
            if byte == SOF:
                self.in_frame = True
                self.escaped = False
                self.payload.clear()
            return None

        if self.escaped:
            self.payload.append(byte)
            self.escaped = False
            return None

        if byte == ESC:
            self.escaped = True
            return None

        if byte == EOF:
            frame = bytes(self.payload)
            self.reset()
            return frame

        if byte == SOF:
            self.payload.clear()
            self.escaped = False
            return None

        self.payload.append(byte)
        return None
