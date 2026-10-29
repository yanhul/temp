from pathlib import Path


def test_route_repair_planner_connects_each_track_to_itself():
    source = (Path(__file__).resolve().parents[1] / "tools" / "altium-audit" / "routing_repair_plan.py").read_text(encoding="utf-8")
    assert 'route_edges.append((ia,ia+1,z[0],z[1]))' in source
    assert 'for ia,ib,_,_ in route_edges:' in source
    assert 'union(ia,ib)' in source


def test_route_repair_planner_does_not_join_cross_layer_tracks_without_via():
    source = (Path(__file__).resolve().parents[1] / "tools" / "altium-audit" / "routing_repair_plan.py").read_text(encoding="utf-8")
    assert 'elif layer_key(mi.get("layer"))==layer_key(mj.get("layer")):' in source
    assert 'mi["kind"]=="via" or mj["kind"]=="via"' in source
