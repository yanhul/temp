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

if __name__=="__main__":
    unittest.main()
