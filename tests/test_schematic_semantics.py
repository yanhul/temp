import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("schematic_semantics", ROOT / "tools" / "altium-audit" / "schematic_semantics.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
audit = module.audit


def _design(*refs):
    return {
        "components": [
            {
                "designator": r,
                "value": "TEST",
                "footprint": "PKG",
                "library_ref": "Lib:Part",
                "classification": {"prefix": r[0], "type": "test", "pin_count": 2},
            }
            for r in refs
        ]
    }


def _net(name, *terms):
    return {"name": name, "terminals": list(terms)}


def _t(ref, pin, ptype="PASSIVE", pname="P"):
    return {"designator": ref, "pin": pin, "pin_name": pname, "pin_type": ptype}


def test_duplicate_component_identity_blocks():
    d = _design("R1")
    d["components"].append(dict(d["components"][0]))
    n = {"components": [{"designator": "R1", "value": "TEST", "footprint": "PKG", "library_ref": "Lib:Part"}],
         "nets": [_net("N1", _t("R1", "1"))]}
    findings = audit(d, n, {"schema": "intent/v1"})
    assert any(x["id"] == "SCH-COMP-DUPLICATE-R1" and x["status"] == "FAIL" for x in findings)


def test_pin_on_multiple_nets_blocks():
    d = _design("U1")
    n = {"components": [{"designator": "U1", "value": "TEST", "footprint": "PKG", "library_ref": "Lib:Part"}],
         "nets": [_net("A", _t("U1", "1")), _net("B", _t("U1", "1"))]}
    findings = audit(d, n, {"schema": "intent/v1"})
    assert any(x["id"] == "SCH-PIN-MULTI-NET-U1-1" and x["status"] == "FAIL" for x in findings)


def test_multiple_driver_net_fails():
    d = _design("U1", "U2")
    n = {"components": [{"designator": r, "value": "TEST", "footprint": "PKG", "library_ref": "Lib:Part"} for r in ("U1", "U2")],
         "nets": [_net("SIG", _t("U1", "1", "OUTPUT"), _t("U2", "1", "OUTPUT"))]}
    findings = audit(d, n, {"schema": "intent/v1"})
    assert any(x["id"] == "SCH-NET-MULTI-DRIVER-SIG" and x["status"] == "FAIL" for x in findings)


def test_missing_functional_intent_is_blocked():
    d = _design("U1")
    n = {"components": [{"designator": "U1", "value": "TEST", "footprint": "PKG", "library_ref": "Lib:Part"}],
         "nets": [_net("SIG", _t("U1", "1"))]}
    findings = audit(d, n, None)
    assert any(x["id"] == "SCH-FUNCTIONAL-INTENT-MISSING" and x["status"] == "BLOCKED" for x in findings)


def test_real_altium_io_pin_type_is_supported():
    d = _design("U1")
    n = {"components": [{"designator": "U1", "value": "TEST", "footprint": "PKG", "library_ref": "Lib:Part"}],
         "nets": [_net("SIG", _t("U1", "1", "IO"))]}
    findings = audit(d, n, {"schema": "intent/v1"})
    assert not any(x["id"] == "SCH-PIN-UNKNOWN-TYPE-U1-1" for x in findings)


def test_parameter_value_satisfies_component_identity():
    d = _design("C2")
    d["components"][0]["value"] = "Cap2"
    d["components"][0]["parameters"] = {"Value": "220uF,16V"}
    n = {"components": [{"designator": "C2", "value": "Cap2", "footprint": "PKG", "library_ref": "Lib:Part"}],
         "nets": [_net("GND", _t("C2", "1"))]}
    findings = audit(d, n, {"schema": "intent/v1"})
    assert not any(x["id"] == "SCH-COMP-MISSING-VALUE-C2" for x in findings)


def test_concrete_identity_drift_blocks():
    d = _design("Q2")
    d["components"][0]["value"] = "BCX56"
    d["components"][0]["parameters"] = {"Value": "C9014"}
    n = {"components": [{"designator": "Q2", "value": "BCX56", "footprint": "PKG", "library_ref": "Lib:Part"}],
         "nets": [_net("SIG", _t("Q2", "1"))]}
    findings = audit(d, n, {"schema": "intent/v1"})
    assert any(x["id"] == "SCH-COMPONENT-IDENTITY-DRIFT-Q2" and x["status"] == "BLOCKED" for x in findings)


def test_library_identity_drift_blocks():
    d = _design("U6")
    d["components"][0]["value"] = "HCPL-0600"
    d["components"][0]["library_ref"] = "IC_HCPL-3120-500E"
    n = {"components": [{"designator": "U6", "value": "HCPL-0600", "footprint": "PKG", "library_ref": "IC_HCPL-3120-500E"}],
         "nets": [_net("SIG", _t("U6", "2"))]}
    findings = audit(d, n, {"schema": "intent/v1", "coverage": "critical_components",
                            "components": {"U6": {"part_numbers": ["HCPL-0600"], "pin_count": 8,
                                                   "pins": {"2": "ANODE"}}}})
    assert any(x["id"] == "SCH-COMPONENT-LIBRARY-DRIFT-U6" for x in findings)


def test_datasheet_pin_count_mismatch_blocks():
    d = _design("U15")
    d["components"][0]["value"] = "ESP32-S3-WROOM-1-N8"
    d["components"][0]["classification"]["pin_count"] = 49
    n = {"components": [{"designator": "U15", "value": "ESP32-S3-WROOM-1-N8", "footprint": "PKG", "library_ref": "ESP32-S3-WROOM-1"}],
         "nets": [_net("SIG", _t("U15", "3", "INPUT", "EN"))]}
    findings = audit(d, n, {"schema": "intent/v1", "coverage": "critical_components",
                            "components": {"U15": {"part_numbers": ["ESP32-S3-WROOM-1-N8"], "pin_count": 41,
                                                   "pins": {"3": "EN"}}}})
    assert any(x["id"] == "SCH-CONTRACT-PINCOUNT-U15" and x["status"] == "FAIL" for x in findings)
