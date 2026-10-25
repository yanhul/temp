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
