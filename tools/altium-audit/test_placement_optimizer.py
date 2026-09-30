import unittest
from placement_optimizer import PlacementConfig, PlacementNode, optimize

class OptimizerTests(unittest.TestCase):
    def test_moves_unlocked_node_toward_affinity_without_moving_anchor(self):
        nodes = [
            PlacementNode("A", (10, 10), (9, 9, 11, 11), locked=True),
            PlacementNode("B", (80, 10), (79, 9, 81, 11)),
        ]
        result = optimize(nodes, {("A", "B"): 10.0}, (0, 0, 100, 100), PlacementConfig(iterations=20))
        moves = {m["reference"]: m for m in result["moves"]}
        self.assertFalse(moves["A"]["changed"])
        self.assertLess(moves["B"]["suggested_target_mils"][0], 80)

    def test_rejects_overlap_improvement_that_leaves_board(self):
        nodes = [
            PlacementNode("A", (5, 5), (0, 0, 10, 10)),
            PlacementNode("B", (50, 50), (45, 45, 55, 55)),
        ]
        result = optimize(nodes, {("A", "B"): 10.0}, (0, 0, 60, 60))
        self.assertLessEqual(result["objective"]["final"]["outside_count"], result["objective"]["initial"]["outside_count"])

if __name__ == "__main__":
    unittest.main()
