import unittest

from topology_candidates import build_geometric_topology


class GeometricTopologyTests(unittest.TestCase):
    def test_t_junction_splits_through_segment_but_does_not_claim_net(self):
        result = build_geometric_topology([
            {"a": [0, 5], "b": [10, 5]},
            {"a": [5, 0], "b": [5, 5]},
        ])
        self.assertEqual(result["input_line_count"], 2)
        self.assertEqual(result["intersection_candidate_count"], 1)
        self.assertEqual(result["split_edge_count"], 3)
        node = result["intersection_candidates"][0]
        self.assertIn("endpoint_on_segment", node["geometry_kinds"])
        self.assertEqual(node["electrical_status"], "UNKNOWN_NO_JUNCTION_AUTHORITY")
        self.assertEqual(result["electrical_connectivity"], "NOT_INFERRED")

    def test_crossing_is_split_into_four_geometric_edges_not_electrically_joined(self):
        result = build_geometric_topology([
            {"a": [0, 5], "b": [10, 5]},
            {"a": [5, 0], "b": [5, 10]},
        ])
        self.assertEqual(result["split_edge_count"], 4)
        self.assertEqual(result["intersection_candidate_count"], 1)
        self.assertIn("interior_crossing", result["intersection_candidates"][0]["geometry_kinds"])
        self.assertTrue(all(edge["electrical_status"] == "GEOMETRY_ONLY_NOT_A_NET" for edge in result["edges"]))

    def test_disjoint_lines_do_not_create_intersection(self):
        result = build_geometric_topology([
            {"a": [0, 0], "b": [2, 0]},
            {"a": [5, 0], "b": [7, 0]},
        ])
        self.assertEqual(result["intersection_candidate_count"], 0)
        self.assertEqual(result["split_edge_count"], 2)

    def test_collinear_overlapping_lines_are_not_guessed_into_intersections(self):
        result = build_geometric_topology([
            {"a": [0, 0], "b": [10, 0]},
            {"a": [5, 0], "b": [15, 0]},
        ])
        self.assertEqual(result["intersection_candidate_count"], 0)
        self.assertEqual(result["electrical_connectivity"], "NOT_INFERRED")

    def test_near_but_not_at_endpoint_is_not_misclassified_as_endpoint(self):
        result = build_geometric_topology([
            {"a": [0, 0], "b": [100, 0]},
            {"a": [1, -2], "b": [1, 2]},
        ])
        node = result["intersection_candidates"][0]
        self.assertIn("interior_crossing", node["geometry_kinds"])
        self.assertNotIn("endpoint_on_segment", node["geometry_kinds"])

    def test_sweep_prunes_parallel_lines_with_disjoint_y_bounds(self):
        lines = [{"a": [0, i * 3], "b": [100, i * 3]} for i in range(100)]
        result = build_geometric_topology(lines)
        self.assertEqual(result["candidate_pair_count"], 0)
        self.assertEqual(result["intersection_candidate_count"], 0)
        self.assertEqual(result["split_edge_count"], 100)

    def test_non_finite_coordinates_are_rejected(self):
        result = build_geometric_topology([
            {"a": [0, 0], "b": [1, 0]},
            {"a": [float("nan"), 0], "b": [2, 2]},
        ])
        self.assertEqual(result["input_line_count"], 1)
        self.assertEqual(result["split_edge_count"], 1)


if __name__ == "__main__":
    unittest.main()
