import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "tools" / "altium-audit" / "audit_kit.py"
FIXTURE = ROOT / "audit-input"

class KitReuseContractTests(unittest.TestCase):
    def test_engine_has_no_fixture_identifiers(self):
        forbidden = ("QI9-2604-A01", "J6", "J7", "ESP32")
        for p in (ROOT / "tools" / "altium-audit").glob("*.py"):
            text = p.read_text(encoding="utf-8")
            self.assertFalse(any(x in text for x in forbidden), p)

    def test_contract_statuses_are_explicit(self):
        plan = (ROOT / "tools" / "altium-audit" / "placement_routing_plan.py").read_text(encoding="utf-8")
        self.assertIn("TOPOLOGY_UNRESOLVED", plan)
        self.assertIn('"VERIFIED"', plan)
        self.assertIn('"UNKNOWN"', plan)
        self.assertIn('"INCOMPLETE"', plan)
        self.assertIn('"BLOCKED"', plan)

    def test_clean_room_input_is_discovered_by_extension_not_name(self):
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "clean-room-input"
            out = Path(td) / "clean-room-output"
            inp.mkdir()
            for src in FIXTURE.iterdir():
                if src.is_file():
                    ext = src.suffix
                    dst = inp / ("CLEANROOM_" + src.stem + "_RENAMED" + ext)
                    shutil.copy2(src, dst)
            proc = subprocess.run(
                [sys.executable, str(KIT), "--input", str(inp), "--output", str(out)],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertTrue((out / "intake.json").exists(), proc.stderr)
            self.assertTrue((out / "summary.json").exists(), proc.stderr)
            intake = json.loads((out / "intake.json").read_text(encoding="utf-8"))
            self.assertTrue(intake["input"]["schematic"].startswith("CLEANROOM_"))
            self.assertTrue(intake["input"]["pcb"].startswith("CLEANROOM_"))

    def test_planner_never_authorizes_topology(self):
        planner = (ROOT / "tools" / "altium-audit" / "placement_routing_plan.py").read_text(encoding="utf-8")
        self.assertIn("PLAN_ONLY_NO_MUTATION", planner)
        self.assertIn("candidate_topology", planner)
        self.assertIn('"NOT_SELECTED"', planner)

if __name__ == "__main__":
    unittest.main()
