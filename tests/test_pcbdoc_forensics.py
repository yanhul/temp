import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "tools" / "altium-audit" / "pcbdoc-forensics"
SCRIPT = ROOT / "explore_format.py"
spec = importlib.util.spec_from_file_location("explore_format", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)

FRAME_SCRIPT = ROOT / "validate_record_framing.py"
frame_spec = importlib.util.spec_from_file_location("validate_record_framing", FRAME_SCRIPT)
framing = importlib.util.module_from_spec(frame_spec)
assert frame_spec and frame_spec.loader
frame_spec.loader.exec_module(framing)


class PcbDocForensicsTests(unittest.TestCase):
    def test_non_ole_input_is_blocked_and_hashed(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "not-a-pcb.bin"
            source.write_bytes(b"not an OLE document")
            report = module.inspect(source)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertFalse(report["ole_signature"])
            self.assertEqual(report["size_bytes"], len(b"not an OLE document"))
            self.assertEqual(len(report["sha256"]), 64)
            self.assertEqual(report["streams"], [])

    def test_ole_magic_is_exact(self):
        self.assertEqual(module.OLE_MAGIC.hex(), "d0cf11e0a1b11ae1")
        self.assertEqual(len(module.OLE_MAGIC), 8)

    def test_valid_track_record_framing(self):
        # Record type 4, followed by little-endian payload length 3 and 3 payload bytes.
        report = framing.analyze_stream(bytes([4, 3, 0, 0, 0, 0xAA, 0xBB, 0xCC]), "Tracks6", 1)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["records_framed"], 1)
        self.assertTrue(report["header_count_matches"])

    def test_truncated_record_fails_closed(self):
        report = framing.analyze_stream(bytes([4, 10, 0, 0, 0, 0xAA]), "Tracks6")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["errors"][0]["error"], "subrecord_out_of_bounds")

    def test_wrong_record_type_fails_closed(self):
        report = framing.analyze_stream(bytes([3, 1, 0, 0, 0, 0xAA]), "Tracks6")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["errors"][0]["error"], "unexpected_record_type")


if __name__ == "__main__":
    unittest.main()
