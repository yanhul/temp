from types import SimpleNamespace
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "altium-audit"))
import audit_runner


def obj(**kwargs):
    return SimpleNamespace(**kwargs)


def pad(ref, pin, x, y, net_index, layer="Top Layer"):
    return obj(component_index=0 if ref == "J1" else 1, designator=pin, x_mils=x, y_mils=y,
               net_index=net_index, layer=layer, width_mils=2, height_mils=2)


def fixture_pcb(pads, tracks, fills=None, regions=None, vias=None):
    return obj(
        components=[obj(designator="J1"), obj(designator="J2")],
        pads=pads,
        tracks=tracks,
        arcs=[],
        vias=vias or [],
        fills=fills or [],
        regions=regions or [],
        nets=[obj(name="GND"), obj(name="VCC")],
    )


def test_topology_never_joins_coincident_tracks_from_different_nets():
    pads = [
        pad("J1", "1", 0, 0, 0), pad("J1", "2", 10, 0, 0),
        pad("J2", "1", 0, 0, 1), pad("J2", "2", 10, 0, 1),
    ]
    tracks = [
        obj(x1=0, y1=0, x2=2, y2=0, net_index=0, layer="Top Layer", width_mils=1),
        obj(x1=8, y1=0, x2=10, y2=0, net_index=0, layer="Top Layer", width_mils=1),
        obj(x1=0, y1=0, x2=2, y2=0, net_index=1, layer="Top Layer", width_mils=1),
        obj(x1=8, y1=0, x2=10, y2=0, net_index=1, layer="Top Layer", width_mils=1),
    ]
    pcb = fixture_pcb(pads, tracks)
    netlist = {"nets": [
        {"name": "GND", "terminals": [{"designator": "J1", "pin": "1"}, {"designator": "J1", "pin": "2"}]},
        {"name": "VCC", "terminals": [{"designator": "J2", "pin": "1"}, {"designator": "J2", "pin": "2"}]},
    ]}
    result = audit_runner.topology_components(pcb, netlist)
    assert result["GND"]["graph_components"] == 2
    assert result["VCC"]["graph_components"] == 2


def test_net_scoped_fill_connects_pad_track_islands_only_on_its_net():
    pads = [pad("J1", "1", 1, 1, 0), pad("J1", "2", 9, 1, 0)]
    tracks = [
        obj(x1=1, y1=1, x2=2, y2=1, net_index=0, layer="Top Layer", width_mils=1),
        obj(x1=8, y1=1, x2=9, y2=1, net_index=0, layer="Top Layer", width_mils=1),
    ]
    fills = [obj(pos1_x_mils=0, pos1_y_mils=0, pos2_x_mils=10, pos2_y_mils=2,
                 net_index=0, layer="Top Layer")]
    pcb = fixture_pcb(pads, tracks, fills=fills)
    netlist = {"nets": [
        {"name": "GND", "terminals": [{"designator": "J1", "pin": "1"}, {"designator": "J1", "pin": "2"}]},
    ]}
    result = audit_runner.topology_components(pcb, netlist)
    assert result["GND"]["graph_components"] == 1
    assert result["GND"]["has_copper_area"] is True


def test_disconnected_net_without_area_remains_two_components(tmp_path):
    pads = [pad("J1", "1", 0, 0, 0), pad("J1", "2", 10, 0, 0)]
    tracks = [
        obj(x1=0, y1=0, x2=2, y2=0, net_index=0, layer="Top Layer", width_mils=1),
        obj(x1=8, y1=0, x2=10, y2=0, net_index=0, layer="Top Layer", width_mils=1),
    ]
    pcb = fixture_pcb(pads, tracks)
    netlist = {"nets": [
        {"name": "GND", "terminals": [{"designator": "J1", "pin": "1"}, {"designator": "J1", "pin": "2"}]},
    ]}
    result = audit_runner.topology_components(pcb, netlist)
    assert result["GND"]["graph_components"] == 2
    assert result["GND"]["has_copper_area"] is False
