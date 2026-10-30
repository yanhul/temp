import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "normalized_ir", "tools/pdf-schematic/build_normalized_ir.py"
)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def test_ir_preserves_provenance_and_does_not_infer_connectivity(tmp_path):
    svg_dir = tmp_path / "svg"
    svg_dir.mkdir()
    primitives = tmp_path / "primitives.json"
    output = tmp_path / "ir.json"
    primitives.write_text(json.dumps({
        "schema": "pdf-schematic-primitives/v1",
        "source": "fixture.pdf",
        "source_sha256": "a" * 64,
        "totals": {"pages": 1},
        "pages": [{
            "page": 1, "width": 100, "height": 100,
            "text_spans": [{"text": "R17", "bbox": [1, 2, 3, 4], "font": "Test", "size": 8}],
        }],
    }))
    (svg_dir / "page1.json").write_text(json.dumps({
        "schema": "pdf-schematic-normalized-geometry/v1",
        "issue_count": 0,
        "issues": [],
        "elements": [{"tag": "path", "segments": []}],
    }))
    import sys
    old_argv = sys.argv
    try:
        sys.argv = ["build_normalized_ir.py", "--svg-dir", str(svg_dir),
                    "--primitives", str(primitives), "--out", str(output)]
        assert MOD.main() == 0
    finally:
        sys.argv = old_argv
    data = json.loads(output.read_text())
    assert data["status"] == "BLOCKED_SYMBOL_PIN_CONNECTIVITY_UNRESOLVED"
    assert data["primitive_count"] == 2
    assert data["pages"][0]["evidence"][0]["authority"] == "OBSERVED_VECTOR_GEOMETRY"
    assert data["pages"][0]["evidence"][1]["text"] == "R17"
    assert data["symbols"] == [] and data["pins"] == []
    assert data["connectivity_edges"] == []
    assert data["policy"]["visual_proximity_is_not_connectivity"] is True


def test_ir_blocks_svg_geometry_issues(tmp_path):
    svg_dir = tmp_path / "svg"
    svg_dir.mkdir()
    primitives = tmp_path / "primitives.json"
    output = tmp_path / "ir.json"
    primitives.write_text(json.dumps({
        "schema": "pdf-schematic-primitives/v1", "source": "x.pdf",
        "source_sha256": "b" * 64, "totals": {"pages": 1},
        "pages": [{"page": 1, "text_spans": []}],
    }))
    (svg_dir / "page1.json").write_text(json.dumps({
        "schema": "pdf-schematic-normalized-geometry/v1",
        "issue_count": 1, "issues": [{"kind": "unresolved_use"}], "elements": [],
    }))
    import sys
    old_argv = sys.argv
    try:
        sys.argv = ["build_normalized_ir.py", "--svg-dir", str(svg_dir),
                    "--primitives", str(primitives), "--out", str(output)]
        assert MOD.main() == 0
    finally:
        sys.argv = old_argv
    data = json.loads(output.read_text())
    assert data["geometry_issues"] == [{"page": 1, "kind": "unresolved_use"}]
    assert data["status"] == "BLOCKED_SYMBOL_PIN_CONNECTIVITY_UNRESOLVED"
