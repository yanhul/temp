from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "altium-audit"))

from part_identity import resolve_declared_vs_compiled


def test_hcpl0600_vs_hcpl3120_is_contradiction_when_pin_fingerprint_matches_compiled():
    pins = {
        "2": {"name": "ANODE"},
        "3": {"name": "CATHODE"},
        "5": {"name": "VEE"},
        "6": {"name": "VO"},
        "7": {"name": "VO"},
        "8": {"name": "VCC"},
    }
    result = resolve_declared_vs_compiled("HCPL-0600", "HCPL-3120", pins)
    assert result["state"] == "CONTRADICTION"


def test_same_identity_is_consistent():
    result = resolve_declared_vs_compiled("HCPL-0600", "HCPL-0600", {})
    assert result["state"] == "CONSISTENT"


def test_unknown_identity_does_not_get_promoted():
    result = resolve_declared_vs_compiled("TL2904", "PC817", {"1": {"name": "A"}})
    assert result["state"] == "UNKNOWN"



def test_smaj15ca_vs_smaj30ca_is_contradiction_on_voltage_rating_even_when_pinout_matches():
    result = resolve_declared_vs_compiled(
        "SMAJ15CA",
        "SMAJ30CA",
        {"1": {"name": "A"}, "2": {"name": "K"}},
    )
    assert result["state"] == "CONTRADICTION"
    assert any(
        item["attribute"] == "reverse_standoff_v"
        and item["declared"] == 15.0
        and item["compiled"] == 30.0
        for item in result["evidence"]
    )


def test_same_smaj_identity_is_consistent_without_pin_evidence():
    result = resolve_declared_vs_compiled("SMAJ15CA", "SMAJ15CA", {})
    assert result["state"] == "CONSISTENT"


def test_unknown_tvs_identity_is_not_assigned_an_invented_voltage_spec():
    result = resolve_declared_vs_compiled("SMAJ9CA", "SMAJ30CA", {})
    assert result["state"] == "UNKNOWN"
