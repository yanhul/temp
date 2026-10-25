import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from benchmark import percentile, summarize


class BenchmarkTests(unittest.TestCase):
    def test_percentile_is_deterministic_for_small_samples(self):
        self.assertEqual(percentile([30, 10, 20], 95), 30.0)
        self.assertIsNone(percentile([], 95))

    def test_all_observed_summary(self):
        summary = summarize([
            {"state": "OBSERVED", "elapsed_ms": 10,
             "usage": {"total_tokens": 8}},
            {"state": "OBSERVED", "elapsed_ms": 30,
             "usage": {"total_tokens": 12}},
        ])
        self.assertEqual(summary["state"], "OBSERVED")
        self.assertEqual(summary["runs"], 2)
        self.assertEqual(summary["latency_ms"]["median"], 20)
        self.assertEqual(summary["provider_total_tokens"], 20)

    def test_unknown_prevents_observed_terminal_state(self):
        summary = summarize([
            {"state": "OBSERVED", "elapsed_ms": 10, "usage": {}},
            {"state": "UNKNOWN", "elapsed_ms": 100, "usage": {}},
        ])
        self.assertEqual(summary["state"], "UNKNOWN")
        self.assertEqual(summary["unknown_runs"], 1)

    def test_blocked_dominates_summary(self):
        summary = summarize([
            {"state": "UNKNOWN", "elapsed_ms": 10, "usage": {}},
            {"state": "BLOCKED", "elapsed_ms": 0, "usage": {}},
        ])
        self.assertEqual(summary["state"], "BLOCKED")
        self.assertEqual(summary["blocked_runs"], 1)


if __name__ == "__main__":
    unittest.main()
