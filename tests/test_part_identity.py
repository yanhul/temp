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
        "7": {"name": "NC"},
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
