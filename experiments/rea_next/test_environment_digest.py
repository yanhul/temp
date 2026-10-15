import unittest

from evidence_graph import Evidence, EvidenceError, EvidenceGraph


ARTIFACT = "a" * 64


class EnvironmentDigestTests(unittest.TestCase):
    def test_verification_rejects_malformed_environment_digest(self):
        graph = EvidenceGraph(ARTIFACT)
        graph.add(Evidence(
            "obs-1", ARTIFACT, "observation", "OBSERVED", "claim", "source"
        ))

        malformed_digests = ("not-a-digest", "g" * 64, "B" * 64)
        for index, digest in enumerate(malformed_digests):
            with self.subTest(digest=digest):
                with self.assertRaisesRegex(
                    EvidenceError, "SHA-256 environment digest"
                ):
                    graph.add(Evidence(
                        f"verify-{index}", ARTIFACT, "verification", "VERIFIED",
                        "claim", "test", ("obs-1",), provider="pytest",
                        environment_digest=digest,
                    ))


if __name__ == "__main__":
    unittest.main()
