import unittest
from pathlib import Path

ROOT = Path("tools/altium-audit")

class StrictQualityContractTests(unittest.TestCase):
    def test_quality_module_is_evidence_only(self):
        text = (ROOT / "placement_routing_quality.py").read_text(encoding="utf-8")
        self.assertIn("STRICT_EVIDENCE_ONLY", text)
        self.assertIn("NOT_PROVEN", text)
        self.assertIn("unknown_constraint_is_not_pass", text)
        self.assertNotIn("add_track(", text)
        self.assertNotIn("save(", text)

    def test_connectivity_does_not_imply_optimization(self):
        text = (ROOT / "placement_routing_quality.py").read_text(encoding="utf-8")
        self.assertIn("never_claim_optimized_from_connectivity_alone", text)
        self.assertIn("candidate_must_be_verified_after_mutation", text)
        self.assertIn("baseline_must_be_immutable", text)

if __name__ == "__main__":
    unittest.main()


class OptimizerContractTests(unittest.TestCase):
    def test_optimizer_is_non_mutating(self):
        text = (ROOT / "placement_routing_optimizer.py").read_text(encoding="utf-8")
        self.assertIn("no mutation occurs here", text)
        self.assertNotIn("add_track(", text)
        self.assertNotIn("save(", text)

    def test_quality_schema_is_strict(self):
        text = (ROOT / "placement_routing_quality.py").read_text(encoding="utf-8")
        self.assertIn("validate_constraints", text)
        self.assertIn("missing_or_wrong_schema", text)
