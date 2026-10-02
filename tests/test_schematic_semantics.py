from tools.altium_audit.schematic_semantics import audit


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
