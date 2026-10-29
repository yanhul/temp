import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "altium-audit"))
from audit_runner import write_schematic_evidence


def test_empty_parameters_do_not_mask_compiled_properties(tmp_path):
    component = {
        "designator": "D12",
        "value": "SMAJ15CA",
        "library_reference": "SMAJ30CA",
        "parameters": {},
        "properties": {
            "Value": {"text": "SMAJ30A"},
            "MPN": {"value": "SMAJ30A"},
            "Footprint": "D_SMA",
        },
    }
    evidence = write_schematic_evidence(tmp_path, [component], {"nets": []})
    record = evidence["components"][0]
    assert record["compiled_value"] == "SMAJ30A"
    assert record["mpn"] == "SMAJ30A"
    assert record["footprint"] == "D_SMA"
    assert record["properties"]["value"] == "SMAJ30A"
    saved = json.loads((tmp_path / "schematic-evidence.json").read_text(encoding="utf-8"))
    assert saved["components"][0]["mpn"] == "SMAJ30A"


def test_typed_property_records_are_preserved_when_both_containers_exist(tmp_path):
    component = {
        "designator": "C2",
        "value": "Cap",
        "parameters": {},
        "properties": [
            {"parameter_name": "Value", "parameter_value": "100nF"},
            {"parameter_name": "MPN", "parameter_value": "GRM188R71H104KA93"},
        ],
    }
    evidence = write_schematic_evidence(tmp_path, [component], {"nets": []})
    record = evidence["components"][0]
    assert record["compiled_value"] == "100nF"
    assert record["mpn"] == "GRM188R71H104KA93"
