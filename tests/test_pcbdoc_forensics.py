import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "altium-audit" / "pcbdoc-forensics" / "explore_format.py"
spec = importlib.util.spec_from_file_location("explore_format", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


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


if __name__ == "__main__":
    unittest.main()
