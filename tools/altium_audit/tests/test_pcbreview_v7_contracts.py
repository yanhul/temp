import unittest

from tools.altium_audit.pcbreview_v7_contracts import (
    PARSER_VERSION, REQUIRED_CONTRACTS, Stage1Gate, all_contracts_verified,
    contract_is_verified, normalize_polygon, resolve_mobility,
)


def verified_statuses():
    return {name: "VERIFIED" for name in REQUIRED_CONTRACTS}


class V7FailClosedTests(unittest.TestCase):
    def test_version_bumped_for_contract_fix(self):
        self.assertEqual(PARSER_VERSION, "pcbreview.parse/7.1")

    def test_used_and_verified_source_are_not_verified(self):
        for status in ("USED_read", "USED_native", "VERIFIED_SOURCE", "PARSED", "PASS", None):
            with self.subTest(status=status):
                self.assertFalse(contract_is_verified(status))

    def test_missing_or_unknown_contract_blocks(self):
        statuses = verified_statuses()
        statuses.pop("netlist_names")
        self.assertFalse(all_contracts_verified(statuses))
        statuses = verified_statuses()
        statuses["pad_units"] = "USED_internal_units"
        self.assertFalse(all_contracts_verified(statuses))

    def test_only_complete_evidence_allows_routing(self):
        good = Stage1Gate(verified_statuses(), True, True, True, True)
        self.assertEqual(good.parse_status, "PARSED_VERIFIED")
        self.assertTrue(good.routing_ready)
        bad = Stage1Gate(verified_statuses(), False, True, True, True)
        self.assertEqual(bad.parse_status, "PARSED_UNVERIFIED")
        self.assertFalse(bad.routing_ready)
        self.assertEqual(bad.geometry_status, "UNVERIFIED")

    def test_geometry_and_electrical_do_not_pass_on_synthetic_contracts(self):
        statuses = verified_statuses()
        statuses["component_api"] = "VERIFIED_SOURCE"
        gate = Stage1Gate(statuses, True, True, True, True)
        self.assertEqual(gate.parse_status, "PARSED_UNVERIFIED")
        self.assertEqual(gate.electrical_status, "UNVERIFIED")
        self.assertFalse(gate.routing_ready)

    def test_polygon_strips_closing_vertex(self):
        polygon = normalize_polygon([(0, 0), (4, 0), (4, 3), (0, 3), (0, 0)])
        self.assertEqual(len(polygon), 4)

    def test_polygon_rejects_degenerate_and_nonfinite(self):
        for points in (
            [(0, 0), (1, 1), (2, 2)],
            [(0, 0), (1, 0), (float("nan"), 1)],
            [(0, 0), (1, 0)],
        ):
            with self.subTest(points=points), self.assertRaises(ValueError):
                normalize_polygon(points)

    def test_policy_override_is_not_source_verification(self):
        mobility, verified = resolve_mobility(source_locked=None, policy_override="FIXED")
        self.assertEqual(mobility, "FIXED")
        self.assertFalse(verified)
        self.assertEqual(resolve_mobility(source_locked=True), ("FIXED", True))
        self.assertEqual(resolve_mobility(source_locked=None), ("UNKNOWN", False))


if __name__ == "__main__":
    unittest.main()
