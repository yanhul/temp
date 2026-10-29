import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "altium-audit"))
import routing_repair_plan as planner


def obj(**kwargs):
    return SimpleNamespace(**kwargs)


def run_plan(monkeypatch, tmp_path, pads, tracks, vias=None):
    pcb = obj(
        nets=[obj(name="N1")],
        get_net_primitives=lambda idx: {
            "pads": pads, "tracks": tracks, "vias": vias or [], "arcs": []
        },
    )
    monkeypatch.setattr(planner.AltiumPcbDoc, "from_file", lambda path: pcb)
    output = tmp_path / "plan.json"
    monkeypatch.setattr(sys, "argv", [
        "routing_repair_plan.py", "--pcb", str(tmp_path / "board.PcbDoc"),
        "--out", str(output)
    ])
    planner.main()
    return json.loads(output.read_text(encoding="utf-8"))


def test_connected_tracks_are_not_misreported_as_disconnected(monkeypatch, tmp_path):
    pads = [
        obj(x_mils=0, y_mils=0, width_mils=2, height_mils=2, layer="Top Layer", designator="1"),
        obj(x_mils=20, y_mils=0, width_mils=2, height_mils=2, layer="Top Layer", designator="2"),
    ]
    tracks = [
        obj(x1=0, y1=0, x2=10, y2=0, layer="Top Layer"),
        obj(x1=10, y1=0, x2=20, y2=0, layer="Top Layer"),
    ]
    result = run_plan(monkeypatch, tmp_path, pads, tracks)
    assert result["nets"] == []


def test_cross_layer_tracks_do_not_connect_without_via(monkeypatch, tmp_path):
    pads = [
        obj(x_mils=0, y_mils=0, width_mils=2, height_mils=2, layer="Top Layer", designator="1"),
        obj(x_mils=10, y_mils=0, width_mils=2, height_mils=2, layer="Bottom Layer", designator="2"),
    ]
    tracks = [
        obj(x1=0, y1=0, x2=5, y2=0, layer="Top Layer"),
        obj(x1=5, y1=0, x2=10, y2=0, layer="Bottom Layer"),
    ]
    result = run_plan(monkeypatch, tmp_path, pads, tracks)
    assert result["nets"][0]["component_count"] == 2


def test_via_is_required_and_sufficient_to_join_layer_transition(monkeypatch, tmp_path):
    pads = [
        obj(x_mils=0, y_mils=0, width_mils=2, height_mils=2, layer="Top Layer", designator="1"),
        obj(x_mils=10, y_mils=0, width_mils=2, height_mils=2, layer="Bottom Layer", designator="2"),
    ]
    tracks = [
        obj(x1=0, y1=0, x2=5, y2=0, layer="Top Layer"),
        obj(x1=5, y1=0, x2=10, y2=0, layer="Bottom Layer"),
    ]
    via = obj(x_mils=5, y_mils=0, diameter_mils=3, layer_start="Top Layer", layer_end="Bottom Layer")
    result = run_plan(monkeypatch, tmp_path, pads, tracks, vias=[via])
    assert result["nets"] == []
