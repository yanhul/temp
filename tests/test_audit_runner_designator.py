import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "altium-audit"))
import audit_runner


class DesignatorRecord:
    def __init__(self, text):
        self.text = text


def test_as_name_handles_typed_designator_parameter():
    class Component:
        name = "Cap2"
        parameters = [DesignatorRecord("C17")]
        children = []
    assert audit_runner.as_name(Component()) == "C17"


def test_as_name_handles_dict_parameters_without_using_symbol_name():
    class Component:
        name = "Cap2"
        parameters = {"Designator": "C17", "Comment": "220uF"}
        children = []
    assert audit_runner.as_name(Component()) == "C17"


def test_as_name_handles_dict_child_record():
    class Component:
        name = "D_Schottky"
        parameters = {}
        children = [{"name": "Designator", "text": "D12"}]
    assert audit_runner.as_name(Component()) == "D12"


def test_as_name_uses_direct_refdes_but_not_generic_name():
    class WithRef:
        name = "Cap2"
        designator = "C3"
        parameters = []
        children = []
    class WithoutRef:
        name = "Cap2"
        parameters = []
        children = []
    assert audit_runner.as_name(WithRef()) == "C3"
    assert audit_runner.as_name(WithoutRef()) is None
