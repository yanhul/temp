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


def test_generated_altium_library_suffix_does_not_fake_authoritative_identity():
    result = resolve_declared_vs_compiled("CH9121T", "ch9121t_c45354919", {})
    assert result["state"] == "UNKNOWN"
    assert "not a pin fingerprint" in result["reason"]


def test_matching_unprofiled_labels_remain_unknown_without_pin_fingerprint():
    result = resolve_declared_vs_compiled("GENERIC_DIODE", "GENERIC_DIODE", {})
    assert result["state"] == "UNKNOWN"


def test_same_identity_is_consistent():
    result = resolve_declared_vs_compiled("HCPL-0600", "HCPL-0600", {})
    assert result["state"] == "CONSISTENT"


def test_same_identity_with_conflicting_observed_pin_functions_is_contradiction():
    observed = {
        "2": {"name": "ANODE"},
        "3": {"name": "CATHODE"},
        "5": {"name": "VEE"},
        "6": {"name": "VO"},
        "7": {"name": "VO"},
        "8": {"name": "VCC"},
    }
    result = resolve_declared_vs_compiled("HCPL-0600", "HCPL-0600", observed)
    assert result["state"] == "CONTRADICTION"
    assert any(item["pin"] == "5" and item["declared_expected"] == "GND"
               and item["observed"] == "VEE" for item in result["evidence"])


def test_identity_override_does_not_waive_conflicting_compiled_pin_map():
    pins = {
        "2": {"name": "ANODE"},
        "3": {"name": "CATHODE"},
        "5": {"name": "VEE"},
        "6": {"name": "VO"},
        "7": {"name": "VO"},
        "8": {"name": "VCC"},
    }
    result = resolve_declared_vs_compiled(
        "HCPL-0600", "HCPL-3120", pins, declared_profile_override="HCPL0600"
    )
    assert result["state"] == "CONTRADICTION"
    assert any(item["pin"] == "5" and item["declared_expected"] == "GND"
               and item["compiled_expected"] == "VEE" for item in result["evidence"])


def test_unknown_identity_does_not_get_promoted():
    result = resolve_declared_vs_compiled("TL2904", "PC817", {"1": {"name": "A"}})
    assert result["state"] == "UNKNOWN"



def test_smaj15ca_vs_smaj30ca_is_contradiction_on_voltage_rating_even_when_pinout_matches():
    result = resolve_declared_vs_compiled(
        "SMAJ15CA",
        "SMAJ30CA",
        {"1": {"name": "A"}, "2": {"name": "K"}},
        compiled_part_identity="SMAJ30CA",
    )
    assert result["state"] == "CONTRADICTION"
    assert any(
        item["attribute"] == "reverse_standoff_v"
        and item["declared"] == 15.0
        and item["compiled"] == 30.0
        for item in result["evidence"]
    )


def test_same_smaj_identity_is_consistent_without_pin_evidence():
    result = resolve_declared_vs_compiled(
        "SMAJ15CA", "SMAJ15CA", {}, compiled_part_identity="SMAJ15CA"
    )
    assert result["state"] == "CONSISTENT"


def test_smaj15ca_vs_smaj30a_detects_voltage_and_directionality_conflict():
    result = resolve_declared_vs_compiled(
        "SMAJ15CA", "SMAJ30A", {}, compiled_part_identity="SMAJ30A"
    )
    assert result["state"] == "CONTRADICTION"
    conflicts = {item["attribute"]: item for item in result["evidence"]}
    assert conflicts["reverse_standoff_v"]["declared"] == 15.0
    assert conflicts["reverse_standoff_v"]["compiled"] == 30.0
    assert conflicts["directionality"]["declared"] == "BIDIRECTIONAL"
    assert conflicts["directionality"]["compiled"] == "UNIDIRECTIONAL"


def test_unknown_tvs_identity_is_not_assigned_an_invented_voltage_spec():
    result = resolve_declared_vs_compiled("SMAJ9CA", "SMAJ30CA", {})
    assert result["state"] == "UNKNOWN"


def test_compiled_symbol_library_is_not_mistaken_for_physical_tvs_identity():
    # The library symbol can share a footprint without proving the user's
    # selected physical TVS part. Without explicit physical identity, fail closed
    # as UNKNOWN instead of manufacturing a voltage/directionality contradiction.
    result = resolve_declared_vs_compiled(
        "SMAJ15CA", "SMAJ30CA", {"1": {"name": "A"}, "2": {"name": "K"}}
    )
    assert result["state"] == "UNKNOWN"
    assert "authoritative pin-function profile" in result["reason"] or "pin fingerprint" in result["reason"]


def test_explicit_physical_tvs_identity_still_detects_spec_contradiction():
    result = resolve_declared_vs_compiled(
        "SMAJ15CA", "SMAJ30CA", {},
        compiled_part_identity="SMAJ30A",
    )
    assert result["state"] == "CONTRADICTION"
    conflicts = {item["attribute"]: item for item in result["evidence"]}
    assert conflicts["reverse_standoff_v"]["compiled"] == 30.0
    assert conflicts["directionality"]["compiled"] == "UNIDIRECTIONAL"
