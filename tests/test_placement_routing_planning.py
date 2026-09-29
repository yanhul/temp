import unittest
from pathlib import Path

ROOT=Path("tools/altium-audit")

class PlanningContractTests(unittest.TestCase):
    def test_planner_is_non_mutating(self):
        text=(ROOT/"placement_routing_plan.py").read_text(encoding="utf-8")
        self.assertIn("PLAN_ONLY_NO_MUTATION",text)
        self.assertIn("TOPOLOGY_UNRESOLVED",text)

    def test_kit_invokes_planner(self):
        text=(ROOT/"audit_kit.py").read_text(encoding="utf-8")
        self.assertIn("placement_routing_plan.py",text)
        self.assertIn("placement-routing-plan.json",text)
        self.assertIn('"kit"',text)
        self.assertIn('"design_status"',text)
        self.assertIn('--connectivity-manifest',text)
        self.assertIn('connectivity_intelligence',text)
        planner=(ROOT/"placement_routing_plan.py").read_text(encoding="utf-8")
        self.assertIn('locked_references',planner)


    def test_geometry_legality_is_not_copper_or_design_specific(self):
        text=(ROOT/"placement_routing_plan.py").read_text(encoding="utf-8")
        self.assertNotIn("get_component_primitives", text)
        self.assertNotIn("COPPER_PRIMITIVES", text)
        for ref in ("U15", "J1", "J2", "J3", "J4", "J5", "J7"):
            self.assertNotIn('"' + ref + '"', text)

if __name__=="__main__":
    unittest.main()


    def test_geometry_legality_is_not_copper_or_design_specific(self):
        text=(ROOT/"placement_routing_plan.py").read_text(encoding="utf-8")
        self.assertNotIn("get_component_primitives", text)
        self.assertNotIn("COPPER_PRIMITIVES", text)
        for ref in ("U15", "J1", "J2", "J3", "J4", "J5", "J7"):
            self.assertNotIn('"' + ref + '"', text)
