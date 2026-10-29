import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "altium-audit"))
import audit_runner


def test_write_schematic_evidence_handles_typed_parameter_list(tmp_path):
    component = {
        "name": "Cap2",
        "parameters": [
            {"type": "AltiumSchDesignator", "name": "Designator", "text": "C17"},
            {"name": "Value", "text": "220uF"},
            {"name": "Footprint", "text": "Cap Pol 3mm"},
        ],
        "pin_count": 2,
    }
    graph = {
        "component_occurrences": [{"id": "occ-C17", "source_designator": "C17"}],
        "terminal_occurrences": [
            {"component_occurrence_ref": "occ-C17", "pin_designator": "1", "name": "POS"},
            {"component_occurrence_ref": "occ-C17", "pin_designator": "2", "name": "NEG"},
        ],
    }
    netlist = {"nets": [
        {"name": "VCC", "terminals": [{"designator": "C17", "pin": "1", "pin_name": "POS"}]},
        {"name": "GND", "terminals": [{"designator": "C17", "pin": "2", "pin_name": "NEG"}]},
    ]}
    evidence = audit_runner.write_schematic_evidence(tmp_path, [component], netlist, compiled_graph=graph)
    assert evidence["status"] == "VERIFIED"
    assert len(evidence["components"]) == 1
    c = evidence["components"][0]
    assert c["reference"] == "C17"
    assert c["properties"]["value"] == "220uF"
    assert c["properties"]["footprint"] == "Cap Pol 3mm"
    assert {p["pin"]: p["connected_net"] for p in c["pins"]} == {"1": "VCC", "2": "GND"}
    assert json.loads((tmp_path / "schematic-evidence.json").read_text()) == evidence


def test_write_schematic_evidence_does_not_use_symbol_name_as_refdes(tmp_path):
    component = {"name": "Cap2", "parameters": [{"name": "Value", "text": "220uF"}], "pin_count": 2}
    evidence = audit_runner.write_schematic_evidence(tmp_path, [component], {"nets": []})
    assert evidence["components"] == []
    assert evidence["status"] == "UNKNOWN"


def test_write_schematic_evidence_supports_netlist_b0_field_aliases(tmp_path):
    component = {"designator": "J1", "parameters": {"Value": "Header"}, "pin_count": 1}
    graph = {
        "component_occurrences": [{"id": "j1-occ", "physical_designator": "J1"}],
        "terminal_occurrences": [
            {"component_occurrence_id": "j1-occ", "physical_pin_designator": "1", "pin_name": "A"}
        ],
    }
    netlist = {"nets": [
        {"name": "UART_RX0", "terminals": [
            {"physical_designator": "J1", "physical_pin_designator": "1", "display_name": "A"}
        ]}
    ]}
    evidence = audit_runner.write_schematic_evidence(tmp_path, [component], netlist, compiled_graph=graph)
    c = evidence["components"][0]
    assert c["reference"] == "J1"
    assert c["pins"][0]["pin"] == "1"
    assert c["pins"][0]["connected_net"] == "UART_RX0"
