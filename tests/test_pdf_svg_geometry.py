import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location("svg_geometry","tools/pdf-schematic/normalize_svg_geometry.py")
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def test_transform_composition_and_point():
    m=mod.parse_transform("translate(10 20) scale(2)")
    x,y=mod.point(m,3,4)
    assert (x,y)==(16,28)

def test_relative_path_and_smooth_curves():
    seg=mod.path_segments("M10 10 l5 0 h5 v5 c1 2 3 4 5 6 s2 3 4 5 q1 2 3 4 t5 6 z")
    assert len(seg)==8
    assert seg[0][0]=="L" and seg[-1][0]=="L"

def test_use_expansion_and_nested_transform(tmp_path):
    svg=tmp_path/"a.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><defs><path id="p" d="M0 0 L2 0"/></defs><g transform="translate(10 0)"><use href="#p" x="3"/></g></svg>')
    out=mod.normalize_svg(svg)
    assert out["element_count"]==1
    pts=out["elements"][0]["segments"][0]["points"]
    assert pts==[[13.0,0.0],[15.0,0.0]]

def test_unresolved_use_is_explicit(tmp_path):
    svg=tmp_path/"a.svg"; svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><use href="#missing"/></svg>')
    out=mod.normalize_svg(svg)
    assert out["issue_count"]==1 and out["issues"][0]["kind"]=="unresolved_use"
