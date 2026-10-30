import importlib.util

spec = importlib.util.spec_from_file_location(
    "connectivity_candidates", "tools/pdf-schematic/build_connectivity_candidates.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def make_ir(elements):
    return {"pages": [{"page": 1, "evidence": [
        {"origin": "normalized_svg", "evidence_id": f"e{i}", "geometry": e}
        for i, e in enumerate(elements)
    ]}]}


def test_endpoint_to_endpoint_is_joined():
    result = mod.build(make_ir([
        {"tag": "line", "segments": [{"type": "L", "points": [[0, 0], [10, 0]]}]},
        {"tag": "line", "segments": [{"type": "L", "points": [[10.01, 0], [20, 0]]}]},
    ]), tolerance=0.05)
    assert result["segment_count"] == 2
    assert len(result["components"]) == 1


def test_crossing_lines_are_not_joined():
    result = mod.build(make_ir([
        {"tag": "line", "segments": [{"type": "L", "points": [[0, 0], [10, 10]]}]},
        {"tag": "line", "segments": [{"type": "L", "points": [[0, 10], [10, 0]]}]},
    ]))
    assert len(result["components"]) == 2
    assert result["policy"]["crossing_connects"] is False


def test_t_junction_without_dot_is_not_joined():
    result = mod.build(make_ir([
        {"tag": "line", "segments": [{"type": "L", "points": [[0, 0], [10, 0]]}]},
        {"tag": "line", "segments": [{"type": "L", "points": [[5, 0], [5, 5]]}]},
    ]))
    assert len(result["components"]) == 2
    assert result["policy"]["endpoint_to_interior_contact_connects"] is False


def test_collinear_overlap_is_recorded_without_false_node_merge():
    result = mod.build(make_ir([
        {"tag": "line", "segments": [{"type": "L", "points": [[0, 0], [10, 0]]}]},
        {"tag": "line", "segments": [{"type": "L", "points": [[5, 0], [15, 0]]}]},
    ]))
    assert result["collinear_overlap_pairs"] == [["e0:s0", "e1:s0"]]
    assert len(result["components"]) == 2
