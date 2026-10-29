#!/usr/bin/env python3
"""Giai doan D: sinh project KiCad 9 tu du lieu da trich xuat — GENERIC."""
import os, re, uuid as _uuid
from collections import defaultdict

PT2MM = 0.35277777
PAPERS = {'A4': (297.0, 210.0), 'A3': (420.0, 297.0), 'A2': (594.0, 420.0),
          'A1': (841.0, 594.0), 'A0': (1189.0, 841.0)}
MARGIN = 22.0
RE_POWER = re.compile(
    r'^(GND.*|.*GND|AGND|DGND|PGND|VCC.*|VDD.*|VSS.*|VBAT.*|VBUS|VIN.*|VOUT.*|'
    r'\+?\d{1,2}V\d*|3V3|1V8|2V5|5VP?|12V|24V|48V|AVDD|DVDD|VREF\+?|V\+|V-)$', re.I)
RE_GND = re.compile(r'^(GND.*|.*GND|AGND|DGND|PGND|VSS.*|0V)$', re.I)


def uid():
    return str(_uuid.uuid4())


def fnum(v):
    s = f'{float(v):.4f}'.rstrip('0').rstrip('.')
    return s if s else '0'


def esc(s):
    return str(s).replace('\\', '\\\\').replace('"', '\\"')


def sym_power(name, gnd_style):
    if gnd_style:
        gfx = ('\n'.join([
            '\t\t\t\t(polyline (pts (xy 0 0) (xy 0 -1.27)) (stroke (width 0.254) (type default)) (fill (type none)))',
            '\t\t\t\t(polyline (pts (xy -1.905 -1.27) (xy 1.905 -1.27)) (stroke (width 0.254) (type default)) (fill (type none)))',
            '\t\t\t\t(polyline (pts (xy -1.27 -2.032) (xy 1.27 -2.032)) (stroke (width 0.254) (type default)) (fill (type none)))',
            '\t\t\t\t(polyline (pts (xy -0.635 -2.794) (xy 0.635 -2.794)) (stroke (width 0.254) (type default)) (fill (type none)))']))
        pin = '\t\t\t(pin power_in line (at 0 0 90) (length 0)\n\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))\n\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))\n\t\t\t)'
    else:
        gfx = '\n'.join([
            '\t\t\t\t(polyline (pts (xy 0 0) (xy 0 2.54)) (stroke (width 0.254) (type default)) (fill (type none)))',
            '\t\t\t\t(polyline (pts (xy -1.27 2.54) (xy 0 3.81) (xy 1.27 2.54) (xy -1.27 2.54)) (stroke (width 0.254) (type default)) (fill (type outline)))'])
        pin = '\t\t\t(pin power_in line (at 0 0 270) (length 0)\n\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))\n\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))\n\t\t\t)'
    return ('\t\t(symbol "power:%s"\n\t\t\t(power)\n\t\t\t(pin_names (hide yes))\n'
            '\t\t\t(exclude_from_sim no) (in_bom no) (on_board yes)\n'
            '\t\t\t(property "Reference" "#PWR" (at 0 %s 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '\t\t\t(property "Value" "%s" (at 0 %s 0) (effects (font (size 1.27 1.27))))\n'
            '\t\t\t(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '\t\t\t(property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '\t\t\t(property "Description" "Power symbol" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '\t\t\t(symbol "%s_0_1"\n%s\n\t\t\t)\n'
            '\t\t\t(symbol "%s_1_1"\n%s\n\t\t\t)\n\t\t)'
            % (name, '-3.81' if gnd_style else '4.5', esc(name),
               '-5.08' if gnd_style else '0', name, gfx, name, pin))


def sym_pwr_flag():
    gfx = ('\t\t\t\t(circle (center 0 1.524) (radius 1.524) (stroke (width 0.254) (type default)) (fill (type none)))\n'
           '\t\t\t\t(polyline (pts (xy -0.762 1.524) (xy 0 2.286) (xy 0.762 0.762)) (stroke (width 0.254) (type default)) (fill (type none)))')
    pin = ('\t\t\t(pin power_in line (at 0 0 270) (length 0)\n'
           '\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))\n'
           '\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))\n\t\t\t)')
    return ('\t\t(symbol "power:PWR_FLAG"\n\t\t\t(power)\n\t\t\t(pin_names (hide yes))\n'
            '\t\t\t(exclude_from_sim no) (in_bom no) (on_board yes)\n'
            '\t\t\t(property "Reference" "#FLG" (at 0 4.2 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '\t\t\t(property "Value" "PWR_FLAG" (at 0 4.5 0) (effects (font (size 1.27 1.27))))\n'
            '\t\t\t(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '\t\t\t(property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '\t\t\t(property "Description" "Power flag" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '\t\t\t(symbol "PWR_FLAG_0_1"\n%s\n\t\t\t)\n'
            '\t\t\t(symbol "PWR_FLAG_1_1"\n%s\n\t\t\t)\n\t\t)' % (gfx, pin))


def sym_box(ref, value, pads_mm, desc='Auto-generated from PDF'):
    xs = [p[1] for p in pads_mm]; ys = [p[2] for p in pads_mm]
    bw = max(4.0, max(xs) - min(xs)); bh = max(4.0, max(ys) - min(ys))
    pins = []
    for num, px, py in pads_mm:
        dx, dy = px, py
        if abs(dx) < 0.01 and abs(dy) < 0.01:
            ang, ln = 270, 0.5
        else:
            import math
            ang = round(math.degrees(math.atan2(dy, dx)))
            ln = 2.54
        pins.append('\t\t\t(pin passive line (at %s %s %d) (length %s)\n'
                    '\t\t\t\t(name "%s" (effects (font (size 1.016 1.016))))\n'
                    '\t\t\t\t(number "%s" (effects (font (size 1.016 1.016))))\n\t\t\t)'
                    % (fnum(px), fnum(py), ang, fnum(ln), esc(num), esc(num)))
    pin_txt = '\n'.join(pins)
    return ('\t\t(symbol "AUTO:%s"\n\t\t\t(pin_names (offset 0.508))\n'
            '\t\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)\n'
            '\t\t\t(property "Reference" "%s" (at 0 %s 0) (effects (font (size 1.27 1.27))))\n'
            '\t\t\t(property "Value" "%s" (at 0 %s 0) (effects (font (size 1.27 1.27))))\n'
            '\t\t\t(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '\t\t\t(property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '\t\t\t(property "Description" "%s" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '\t\t\t(symbol "%s_0_1"\n\t\t\t\t(rectangle (start %s %s) (end %s %s)\n'
            '\t\t\t\t\t(stroke (width 0.254) (type default)) (fill (type background)))\n\t\t\t)\n'
            '\t\t\t(symbol "%s_1_1"\n%s\n\t\t\t)\n\t\t)'
            % (esc(ref), esc(ref[0] if not ref[0].isdigit() else 'U'),
               fnum(bh / 2 + 1.6), esc(value), fnum(-bh / 2 - 1.6), esc(desc),
               esc(ref), fnum(-bw / 2), fnum(bh / 2), fnum(bw / 2), fnum(-bh / 2),
               esc(ref), pin_txt))
