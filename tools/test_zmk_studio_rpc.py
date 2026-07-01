from __future__ import annotations

import unittest

from zmk_studio_rpc.framing import EOF, ESC, SOF, FrameDecoder, encode_frame
from zmk_studio_rpc.proto import ProtoBundle, find_proto_file


class FramingTest(unittest.TestCase):
    def test_round_trip_with_special_bytes(self) -> None:
        payload = bytes([0x12, SOF, 0x34, ESC, 0x56, EOF])
        framed = encode_frame(payload)

        self.assertEqual(framed[0], SOF)
        self.assertEqual(framed[-1], EOF)
        self.assertIn(bytes([ESC, SOF]), framed)
        self.assertIn(bytes([ESC, ESC]), framed)
        self.assertIn(bytes([ESC, EOF]), framed)

        decoder = FrameDecoder()
        self.assertEqual(decoder.feed(framed), [payload])

    def test_decoder_ignores_noise_before_sof(self) -> None:
        decoder = FrameDecoder()
        framed = bytes([0x00, 0x01]) + encode_frame(b"abc")
        self.assertEqual(decoder.feed(framed), [b"abc"])


class ProtoBundleTest(unittest.TestCase):
    def test_loads_official_and_custom_messages(self) -> None:
        workspace = ".work/zmk-keyboard-abyss-tester-xiao"
        devtool = find_proto_file(workspace, "proto/cormoran/devtool/devtool.proto")
        bundle = ProtoBundle.from_workspace(workspace, custom_proto_files=[devtool])

        self.assertEqual(bundle.studio.Request.DESCRIPTOR.full_name, "zmk.studio.Request")
        self.assertEqual(bundle.core.Request.DESCRIPTOR.full_name, "zmk.core.Request")
        self.assertEqual(
            bundle.message_class("cormoran.devtool.Request").DESCRIPTOR.full_name,
            "cormoran.devtool.Request",
        )


if __name__ == "__main__":
    unittest.main()
