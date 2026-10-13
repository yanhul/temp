import unittest

from evidence_graph import Evidence, EvidenceError, EvidenceGraph

ARTIFACT = "a" * 64
ENV = "b" * 64


class EvidenceGraphTests(unittest.TestCase):
    def setUp(self):
        self.graph = EvidenceGraph(ARTIFACT)

    def observation(self, evidence_id="obs-1", claim="function returns zero"):
        item = Evidence(evidence_id, ARTIFACT, "observation", "OBSERVED", claim,
                        "disassembler:listing", provider="ghidra")
        self.graph.add(item)
        return item

    def test_no_pass_without_verification(self):
        self.observation()
        self.assertEqual(self.graph.terminal_state(["function returns zero"]), "INCONCLUSIVE")

    def test_verified_claim_requires_observation_lineage(self):
        self.observation()
        self.graph.add(Evidence("verify-1", ARTIFACT, "verification", "VERIFIED",
                                "function returns zero", "regression-test",
                                ("obs-1",), provider="pytest", environment_digest=ENV))
        self.assertEqual(self.graph.terminal_state(["function returns zero"]), "PASS")
        self.assertEqual([x.evidence_id for x in self.graph.lineage("verify-1")],
                         ["obs-1", "verify-1"])

    def test_contradiction_prevents_pass(self):
        self.observation()
        self.graph.add(Evidence("verify-1", ARTIFACT, "verification", "VERIFIED",
                                "function returns zero", "regression-test",
                                ("obs-1",), provider="pytest", environment_digest=ENV))
        self.graph.add(Evidence("contradiction-1", ARTIFACT, "observation", "CONTRADICTED",
                                "function returns zero", "independent-reproduction"))
        self.assertEqual(self.graph.terminal_state(["function returns zero"]), "INCONCLUSIVE")

    def test_rejects_artifact_mismatch(self):
        with self.assertRaises(EvidenceError):
            self.graph.add(Evidence("obs-1", "c" * 64, "observation", "OBSERVED",
                                    "claim", "source"))

    def test_rejects_verified_inference(self):
        with self.assertRaises(EvidenceError):
            self.graph.add(Evidence("inf-1", ARTIFACT, "inference", "VERIFIED",
                                    "claim", "model"))

    def test_rejects_missing_parent(self):
        with self.assertRaises(EvidenceError):
            self.graph.add(Evidence("verify-1", ARTIFACT, "verification", "VERIFIED",
                                    "claim", "test", ("missing",), provider="pytest",
                                    environment_digest=ENV))

    def test_rejects_duplicate_ids(self):
        self.observation()
        with self.assertRaises(EvidenceError):
            self.observation()

    def test_empty_requirements_do_not_pass(self):
        self.assertEqual(self.graph.terminal_state([]), "INCONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
