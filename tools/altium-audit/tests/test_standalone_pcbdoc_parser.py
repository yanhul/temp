import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "standalone_pcbdoc_parser.py"
SPEC = importlib.util.spec_from_file_location("standalone_pcbdoc_parser", MODULE_PATH)
parser = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parser)


def test_pad_bbox_unrotated_rectangle():
    pad = {"layer": 1, "topw": 200, "toph": 100, "x": 1000, "y": 2000, "rot": 0}
    assert parser.pad_bbox(pad) == (900.0, 1950.0, 1100.0, 2050.0)


def test_pad_bbox_90_degree_rotation_swaps_extents():
    pad = {"layer": 1, "topw": 200, "toph": 100, "x": 1000, "y": 2000, "rot": 90}
    box = parser.pad_bbox(pad)
    assert abs((box[2] - box[0]) - 100) < 1e-8
    assert abs((box[3] - box[1]) - 200) < 1e-8
    assert abs((box[0] + box[2]) / 2 - 1000) < 1e-8
    assert abs((box[1] + box[3]) / 2 - 2000) < 1e-8


def test_pad_bbox_45_degree_rotation_is_conservative():
    pad = {"layer": 1, "topw": 200, "toph": 100, "x": 0, "y": 0, "rot": 45}
    x1, y1, x2, y2 = parser.pad_bbox(pad)
    assert x2 - x1 > 200
    assert y2 - y1 > 200
    assert x1 < 0 < x2 and y1 < 0 < y2



def test_render_board_svg_writes_top_bottom_and_manifest(tmp_path):
    pcb = {
        "true_outline": {"outline_polygon": [(0, 0), (1000000, 0), (1000000, 800000), (0, 800000)]},
        "tracks": [{"layer": 1, "x1": 100000, "y1": 100000, "x2": 500000, "y2": 100000, "width": 1000}],
        "pads": [{"layer": 1, "x": 200000, "y": 200000, "topw": 20000, "toph": 20000, "botw": 20000, "both": 20000}],
        "vias": [{"x": 500000, "y": 400000, "diameter": 30000}],
        "arcs": [],
        "components": [{"X": "200000", "Y": "200000", "SOURCEDESIGNATOR": "U1"}],
        "source": {"sha256": "abc123"},
    }
    summary = parser.render_board_svg(pcb, tmp_path)
    assert summary["status"] == "RENDERED_PREVIEWS"
    assert (tmp_path / "top.svg").read_text().startswith("<svg")
    assert (tmp_path / "bottom.svg").read_text().startswith("<svg")
    assert "U1" in (tmp_path / "top.svg").read_text()
    assert '"source_modified": false' in (tmp_path / "svg-summary.json").read_text()
