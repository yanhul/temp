import importlib.util
import hashlib
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "converted_netlist", "tools/pdf-schematic/import_converted_kicad_netlist.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PROVENANCE = {
    "source_schdoc": "source.SchDoc",
    "source_schdoc_sha256": "a" * 64,
    "converted_kicad_sch": "converted.kicad_sch",
    "converted_kicad_sch_sha256": "b" * 64,
    "netlist": "netlist.xml",
    "netlist_sha256": "c" * 64,
}

XML = """<?xml version="1.0" encoding="UTF-8"?>
<export version="E">
  <components>
    <comp ref="R1"><value>10k</value><footprint>Resistor_SMD:R_0603</footprint>
      <libsource lib="Device" part="R"/></comp>
    <comp ref="U1"><value>IC</value><libsource lib="MCU" part="MCU_Generic"/></comp>
  </components>
  <nets>
    <net code="1" name="GND">
      <node ref="R1" pin="2" pinfunction="2" pintype="passive"/>
      <node ref="U1" pin="4" pinfunction="GND" pintype="power_in"/>
    </net>
    <net code="2" name="VCC">
      <node ref="R1" pin="1" pinfunction="1" pintype="passive"/>
    </net>
  </nets>
</export>
"""


def test_imports_exact_component_pin_and_net_membership_without_claiming_native_truth():
    result = mod.build(XML, PROVENANCE, [{"x": 12.5, "y": 8.0,
                                         "authority": "EXPLICIT_CONVERTED_KICAD_JUNCTION_OBJECT"}])
    assert result["counts"] == {
        "symbol_count": 2,
        "resolved_pin_membership_count": 3,
        "net_count": 2,
        "explicit_junction_object_count": 1,
    }
    assert result["symbols"][0]["reference"] == "R1"
    assert result["pins"][0]["reference"] == "R1"
    assert result["nets"][0]["name"] == "GND"
    assert result["status"] == "CONVERTED_UNVERIFIED_NATIVE_ALTIUM_EQUIVALENCE"
    assert result["policy"]["native_altium_equivalence_claimed"] is False
    assert result["policy"]["pin_numbers_inferred"] is False


def test_rejects_missing_provenance_hash():
    bad = dict(PROVENANCE)
    bad["source_schdoc_sha256"] = ""
    with pytest.raises(ValueError, match="provenance hash"):
        mod.build(XML, bad)


def test_rejects_duplicate_component_reference():
    xml = XML.replace(
        '<comp ref="U1"><value>IC</value><libsource lib="MCU" part="MCU_Generic"/></comp>',
        '<comp ref="R1"><value>IC</value><libsource lib="MCU" part="MCU_Generic"/></comp>',
    )
    with pytest.raises(ValueError, match="duplicate component"):
        mod.build(xml, PROVENANCE)


def test_rejects_pin_assigned_to_two_nets():
    xml = XML.replace(
        '<node ref="R1" pin="1" pinfunction="1" pintype="passive"/>',
        '<node ref="R1" pin="2" pinfunction="1" pintype="passive"/>',
    )
    with pytest.raises(ValueError, match="more than one net"):
        mod.build(xml, PROVENANCE)


def test_rejects_unknown_component_pin_reference():
    xml = XML.replace('ref="U1" pin="4"', 'ref="U99" pin="4"')
    with pytest.raises(ValueError, match="unknown component"):
        mod.build(xml, PROVENANCE)


def test_extracts_only_explicit_kicad_junction_objects(tmp_path):
    schematic = tmp_path / "converted.kicad_sch"
    schematic.write_text(
        '(kicad_sch (version 20250114) '
        '(junction (at 12.5 8.0) (diameter 0) (color 0 0 0 0)) '
        '(wire (pts (xy 1 1) (xy 2 2))))',
        encoding="utf-8",
    )
    assert mod.extract_explicit_junctions(schematic) == [{
        "x": 12.5, "y": 8.0,
        "authority": "EXPLICIT_CONVERTED_KICAD_JUNCTION_OBJECT",
    }]


def test_rejects_malformed_junction_coordinates(tmp_path):
    schematic = tmp_path / "bad.kicad_sch"
    schematic.write_text('(kicad_sch (junction (diameter 0)))', encoding="utf-8")
    with pytest.raises(ValueError, match="lacks a valid"):
        mod.extract_explicit_junctions(schematic)
