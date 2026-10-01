import json
import unittest
from pathlib import Path

ROOT=Path("tools/altium-audit")

class AnchorFirstPlacementTests(unittest.TestCase):
    def test_generic_engine_has_no_qi9_refs(self):
        text=(ROOT/"placement_engine.py").read_text(encoding="utf-8")
        for ref in ("J1","J2","J3","J4","J5","J7","U15"):
            self.assertNotIn('"' + ref + '"',text)

    def test_qi9_authority_declares_hard_anchors(self):
        d=json.loads((ROOT/"authority/QI9-2604-A01-placement.json").read_text())
        self.assertEqual(d["schema"],"altium-placement-authority.v1")
        self.assertEqual({k for k,v in d["anchors"].items() if v["state"]=="FIXED"},
                         {"J1","J2","J3","J4","J5","J7","U15"})

    def test_fixed_anchor_constraints_are_hard(self):
        d=json.loads((ROOT/"authority/QI9-2604-A01-placement.json").read_text())
        for ref in ("J1","J2","J3","J4","J5","J7","U15"):
            self.assertEqual(d["anchors"][ref]["state"],"FIXED")
            self.assertEqual(d["anchors"][ref]["position"],"source_pcbdoc")
            self.assertEqual(d["anchors"][ref]["orientation"],"source_pcbdoc")
            self.assertEqual(d["anchors"][ref]["mechanical_envelope"],"source_pcbdoc")


    def test_qi9_assembly_access_is_explicit_authority(self):
        d=json.loads((ROOT/"authority/QI9-2604-A01-placement.json").read_text())
        self.assertEqual(d["assembly_access"]["status"],"BASELINE_VERIFIED")
        self.assertEqual(
            d["assembly_access"]["project_specific_fabricator_process"]["status"],
            "MISSING",
        )

    def test_generic_engine_remains_project_agnostic(self):
        text=(ROOT/"placement_engine.py").read_text(encoding="utf-8")
        self.assertNotIn("QI9-2604-A01",text)


    def test_placement_engine_has_global_legality_gates(self):
        text=(ROOT/"placement_engine.py").read_text(encoding="utf-8")
        for marker in (
            "global placement reservation",
            "BOARD_BOUNDS",
            "KEEPOUT_OVERLAP",
            "COMPONENT_COURTYARD_OVERLAP",
            "FINAL_GLOBAL_RECHECK",
        ):
            self.assertIn(marker,text)

    def test_rotation_fails_closed_without_explicit_geometry(self):
        text=(ROOT/"placement_engine.py").read_text(encoding="utf-8")
        self.assertIn("ROTATION_GEOMETRY_UNAVAILABLE",text)
        self.assertIn("geometry_exact",text)

    def test_optimizer_has_no_pcbdoc_mutation(self):
        text=(ROOT/"placement_engine.py").read_text(encoding="utf-8")
        self.assertIn('"mutation":"FORBIDDEN"',text)
