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


def line(a, b):
    return {"tag": "line", "segments": [{"type": "L", "points": [a, b]}]}


def test_endpoint_to_endpoint_uses_one_canonical_node():
    result = mod.build(make_ir([
        line([0, 0], [10, 0]),
        line([10.01, 0], [20, 0]),
    ]), tolerance=0.05)
    assert result["segment_count"] == 2
    assert len(result["components"]) == 1
    node_ids = {node["node_id"] for node in result["nodes"]}
    assert all(edge["from"] in node_ids and edge["to"] in node_ids for edge in result["edges"])
    shared = set(result["edges"][0].values()) & set(result["edges"][1].values())
    assert result["edges"][0]["to"] == result["edges"][1]["from"]


def test_endpoint_snap_checks_adjacent_spatial_hash_buckets():
    result = mod.build(make_ir([
        line([-1, 0], [0.049, 0]),
        line([0.051, 0], [1, 0]),
    ]), tolerance=0.05)
    assert len(result["components"]) == 1


def test_crossing_lines_are_not_joined():
    result = mod.build(make_ir([
        line([0, 0], [10, 10]),
        line([0, 10], [10, 0]),
    ]))
    assert len(result["components"]) == 2
    assert result["policy"]["crossing_connects"] is False


def test_non_collinear_t_junction_without_authority_is_not_joined():
    result = mod.build(make_ir([
        line([0, 0], [10, 0]),
        line([5, 0], [5, 5]),
    ]))
    assert len(result["components"]) == 2
    assert result["policy"]["non_collinear_t_junction_connects"] is False


def test_collinear_overlap_is_split_and_connected():
    result = mod.build(make_ir([
        line([0, 0], [10, 0]),
        line([5, 0], [15, 0]),
    ]))
    assert result["collinear_overlap_pairs"] == [["e0:s0", "e1:s0"]]
    assert result["segment_count"] == 2
    assert result["edge_count"] == 4
    assert len(result["components"]) == 1
    assert result["policy"]["collinear_overlap_connects"] is True


def test_edge_references_are_canonical_and_components_match_edges():
    result = mod.build(make_ir([
        line([0, 0], [10, 0]),
        line([10, 0], [20, 0]),
        line([100, 0], [110, 0]),
    ]))
    node_ids = {node["node_id"] for node in result["nodes"]}
    component_ids = {node_id for component in result["components"] for node_id in component["node_ids"]}
    assert component_ids == node_ids
    assert all(edge["from"] in node_ids and edge["to"] in node_ids for edge in result["edges"])
    assert len(result["components"]) == 2


def test_result_is_independent_of_input_segment_order():
    elements = [line([0, 0], [10, 0]), line([5, 0], [15, 0]), line([30, 0], [40, 0])]
    first = mod.build(make_ir(elements))
    second = mod.build(make_ir(list(reversed(elements))))
    assert first["nodes"] == second["nodes"]
    # Evidence IDs follow source order in this fixture, so compare topology only.
    assert sorted((e["page"], e["from"], e["to"]) for e in first["edges"]) == sorted(
        (e["page"], e["from"], e["to"]) for e in second["edges"]
    )


def test_invalid_tolerance_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        mod.build(make_ir([]), tolerance=0)
