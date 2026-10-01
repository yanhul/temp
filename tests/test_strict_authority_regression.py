import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "altium-audit" / "audit_runner.py"
KIT = ROOT / "tools" / "altium-audit" / "audit_kit.py"

class StrictAuthorityRegression(unittest.TestCase):
    def test_direct_schdoc_cannot_fabricate_compiled_netlist(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertNotIn('netlist = {"nets": []}', source)
        self.assertIn("G3-NETLIST-AUTHORITY", source)
        self.assertIn("Direct SchDoc parsing is structural-only", source)

    def test_pcb_binary_structure_is_explicitly_gated(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("AltiumPcbDoc.from_file", source)
        self.assertIn("G4-PCB-STRUCTURE", source)
        self.assertIn("pcb_components", source)
        self.assertIn("pcb_pads", source)

    def test_fallback_planning_uses_fallback_evidence(self):
        source = KIT.read_text(encoding="utf-8")
        self.assertIn('evidence_out = out/"audit-direct-fallback" if fallback else audit_out', source)
        self.assertIn('evidence_out/"findings.json"', source)

if __name__ == "__main__":
    unittest.main()
