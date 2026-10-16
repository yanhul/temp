import unittest

from evidence_graph import Evidence, EvidenceError, EvidenceGraph

ARTIFACT = "a" * 64
ENV = "b" * 64


class EqualitySpoof:
    """Runtime value that claims equality with a digest despite not being text."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False


class EvidenceGraphTests(unittest.TestCase):
    def setUp(self):
        self.graph = EvidenceGraph(ARTIFACT)

    def observation(self, evidence_id="obs-1", claim="function returns zero", status="OBSERVED"):
        item = Evidence(evidence_id, ARTIFACT, "observation", status, claim,
                        "disassembler:listing", provider="ghidra")
        self.graph.add(item)
        return item

    def verification(self, evidence_id="verify-1", claim="function returns zero", parents=("obs-1",)):
        self.graph.add(Evidence(evidence_id, ARTIFACT, "verification", "VERIFIED",
                                claim, "regression-test", parents,
                                provider="pytest", environment_digest=ENV))

    def test_rejects_non_evidence_record(self):
        with self.assertRaisesRegex(EvidenceError, "Evidence record"):
            self.graph.add({"evidence_id": "obs-1"})

    def test_rejects_artifact_digest_object_that_spoofs_equality(self):
        item = Evidence("obs-spoof", EqualitySpoof(), "observation", "OBSERVED",
                        "claim", "source")
        with self.assertRaisesRegex(EvidenceError, "artifact_sha256 must be"):
            self.graph.add(item)
        self.assertEqual(self.graph.items, ())

    def test_rejects_malformed_artifact_digest_before_comparison(self):
        for digest in ("A" * 64, "a" * 63, "g" * 64, None):
            with self.subTest(digest=digest):
                item = Evidence("obs-bad", digest, "observation", "OBSERVED",
                                "claim", "source")
                with self.assertRaisesRegex(EvidenceError, "artifact_sha256 must be"):
                    self.graph.add(item)
                self.assertEqual(self.graph.items, ())

    def test_verification_rejects_non_string_provider(self):
        self.observation()
        with self.assertRaisesRegex(EvidenceError, "named verifier"):
            self.graph.add(Evidence("verify-bad", ARTIFACT, "verification", "VERIFIED",
                                    "function returns zero", "test", ("obs-1",),
                                    provider=None, environment_digest=ENV))

    def test_verification_rejects_non_string_environment_digest(self):
        self.observation()
        with self.assertRaisesRegex(EvidenceError, "environment digest"):
            self.graph.add(Evidence("verify-bad", ARTIFACT, "verification", "VERIFIED",
                                    "function returns zero", "test", ("obs-1",),
                                    provider="pytest", environment_digest=None))

    def test_no_pass_without_verification(self):
        self.observation()
        self.assertEqual(self.graph.terminal_state(["function returns zero"]), "INCONCLUSIVE")

    def test_verified_claim_requires_observation_lineage(self):
        self.observation()
        self.verification()
        self.assertEqual(self.graph.terminal_state(["function returns zero"]), "PASS")
        self.assertEqual([x.evidence_id for x in self.graph.lineage("verify-1")],
                         ["obs-1", "verify-1"])

    def test_contradiction_prevents_pass(self):
        self.observation()
        self.verification()
        self.observation("contradiction-1", status="CONTRADICTED")
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

    def test_string_requirement_is_not_iterated_as_character_claims(self):
        self.assertEqual(self.graph.terminal_state("claim"), "INCONCLUSIVE")

    def test_none_requirements_fail_closed(self):
        self.assertEqual(self.graph.terminal_state(None), "INCONCLUSIVE")

    def test_failing_requirement_iterator_fails_closed(self):
        def broken():
            yield "claim"
            raise RuntimeError("broken iterable")
        self.assertEqual(self.graph.terminal_state(broken()), "INCONCLUSIVE")

    def test_lineage_rejects_non_string_id_with_domain_error(self):
        with self.assertRaisesRegex(EvidenceError, "non-empty string"):
            self.graph.lineage([])

    def test_unknown_observation_cannot_verify_claim(self):
        self.observation(status="UNKNOWN")
        with self.assertRaises(EvidenceError):
            self.verification()

    def test_contradicted_observation_cannot_verify_claim(self):
        self.observation(status="CONTRADICTED")
        with self.assertRaises(EvidenceError):
            self.verification()

    def test_verification_cannot_use_different_claim_observation(self):
        self.observation(claim="different claim")
        with self.assertRaises(EvidenceError):
            self.verification()

    def test_verification_rejects_invalid_status(self):
        self.observation()
        with self.assertRaises(EvidenceError):
            self.graph.add(Evidence("verify-bad", ARTIFACT, "verification", "OBSERVED",
                                    "function returns zero", "test", ("obs-1",),
                                    provider="pytest", environment_digest=ENV))


    def test_rejects_string_subclass_for_kind(self):
        class KindString(str):
            pass
        with self.assertRaisesRegex(EvidenceError, "kind must be a plain string"):
            self.graph.add(Evidence("obs-kind-subclass", ARTIFACT, KindString("observation"),
                                    "OBSERVED", "claim", "source"))
        self.assertEqual(self.graph.items, ())

    def test_rejects_string_subclass_for_status(self):
        class StatusString(str):
            pass
        with self.assertRaisesRegex(EvidenceError, "status must be a plain string"):
            self.graph.add(Evidence("obs-status-subclass", ARTIFACT, "observation",
                                    StatusString("OBSERVED"), "claim", "source"))
        self.assertEqual(self.graph.items, ())


if __name__ == "__main__":
    unittest.main()
