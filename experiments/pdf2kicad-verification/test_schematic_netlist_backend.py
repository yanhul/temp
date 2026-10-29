import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from schematic_netlist_backend import run_backend


class BackendAdapterTests(unittest.TestCase):
    def test_missing_backend_fails_closed(self):
        with tempfile.TemporaryDirectory() as td, patch("schematic_netlist_backend.shutil.which", return_value=None):
            result = run_backend("input.pdf", td)
            self.assertEqual(result["status"], "UNAVAILABLE")
            self.assertFalse(result["verified_netlist"])
            self.assertFalse(result["verified_kicad"])
            self.assertEqual(json.loads((Path(td) / "external_backend_manifest.json").read_text())["status"], "UNAVAILABLE")

    def test_success_is_still_unverified(self):
        proc = Mock(returncode=0, stdout="ok", stderr="")
        with tempfile.TemporaryDirectory() as td, patch("schematic_netlist_backend.shutil.which", return_value="/usr/bin/schematic-netlist"), patch("schematic_netlist_backend.subprocess.run", return_value=proc):
            result = run_backend("input.pdf", td, "5-13")
            self.assertEqual(result["status"], "EXTRACTED_UNVERIFIED")
            self.assertFalse(result["verified_netlist"])
            self.assertFalse(result["verified_kicad"])
            self.assertIn("--pages", result["command"])
            self.assertTrue((Path(td) / "external_backend_stdout.txt").exists())

    def test_backend_failure_is_recorded(self):
        proc = Mock(returncode=2, stdout="", stderr="parse failed")
        with tempfile.TemporaryDirectory() as td, patch("schematic_netlist_backend.shutil.which", return_value="/usr/bin/schematic-netlist"), patch("schematic_netlist_backend.subprocess.run", return_value=proc):
            result = run_backend("input.pdf", td)
            self.assertEqual(result["status"], "FAILED")
            self.assertFalse(result["verified_netlist"])


if __name__ == "__main__":
    unittest.main()
