#!/usr/bin/env python3
"""3D-printable enclosure for the Office AC perfboard (5 x 7 cm, uncut), in build123d.

The board sits on four standoffs under its corner mounting holes (M2 self-tapping
screws). The lid screws onto four corner bosses (M3 self-tapping screws).

Board geometry follows tools/perfboard.py: columns A-R across the 50 mm side,
rows 1-24 along the 70 mm side, row 1 at the USB end, 2.54 mm pitch. Seen from
above with the USB end towards you, column A is on the left. In this model:
    +X  towards column R (the LED wall, faces the AC)
    -Y  towards row 1 (the USB wall)
    +Z  up, Z = 0 is the underside of the base

Parameters marked MEASURE are estimates. Check them with calipers before the
full print, or print fit_test.stl first: it is the floor, the standoffs and the
bottom of the walls, so you can screw the board down and check the holes line up.

Usage:
    python enclosure/perfboard_box.py            # export STL/STEP, preview if possible
    python enclosure/perfboard_box.py --no-show  # export only
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

from build123d import (
    Align,
    Box,
    Compound,
    Cylinder,
    Part,
    Pos,
    RectangleRounded,
    export_step,
    export_stl,
    extrude,
)

OUT_DIR = Path(__file__).resolve().parent / "out"

# --------------------------------------------------------------------------
# Parameters (mm)
# --------------------------------------------------------------------------

# Perfboard (tools/perfboard.py, final-build-guide.md).
PITCH = 2.54
COLS, ROWS = 18, 24
BOARD_W, BOARD_L, BOARD_T = 50.0, 70.0, 1.6
# Corner mounting holes: Adafruit's spec for this board style. MEASURE: centre
# to centre across (W) and along (L), and the hole diameter.
MOUNT_PITCH_W, MOUNT_PITCH_L = 46.4, 66.0
MOUNT_HOLE_D = 2.0

# Board standoffs: M2 x 6 self-tapping screws (1.6 mm board + 4.4 mm into plastic).
STANDOFF_H = 5.0            # clearance under the board for solder joints and pins
STANDOFF_D = 5.0
STANDOFF_PILOT_D = 1.7      # M2 self-tapper into PLA
STANDOFF_RIB_W = 3.0        # ties each standoff to its end wall (no thin slivers)

# Gaps between board edges and inside walls.
GAP_LEFT = 8.0              # column A side: room for the lid bosses
GAP_RIGHT = 10.5            # column R side: LEDs stick out about 10 mm. MEASURE
GAP_END = 1.0               # both short ends; keeps the USB socket near the wall

# Components above the board's top surface. MEASURE both.
TALLEST_ABOVE_BOARD = 16.5  # sockets 8.5 + header spacer 2.5 + ESP32 PCB 1.6 + module
TOP_CLEARANCE = 3.0

# Shell.
WALL = 2.0
FLOOR = 2.0
LID_T = 2.0
CORNER_R = 3.0              # outside corner radius

# Lid bosses: M3 x 8 self-tapping screws.
LID_BOSS_D = 6.0
LID_PILOT_D = 2.5
LID_PILOT_DEPTH = 10.0
LID_HOLE_D = 3.4
BOSS_OVERLAP = 0.5          # bosses sink into the walls; exact tangency breaks the STL

# USB slot in the row-1 wall, centred on the ESP32 (midway between columns A and K).
USB_SLOT_W, USB_SLOT_H = 13.0, 8.0
USB_Z_ABOVE_BOARD = 14.0    # connector centre above the board's top surface. MEASURE

# IR LED window in the column-R wall, spanning both LEDs (rows 7-8 and 10-11).
LED_ROWS = (7, 8, 10, 11)
LED_D = 5.0
LED_WINDOW_MARGIN = 3.0     # each end, for the ~10 degree splay between the LEDs
LED_WINDOW_BELOW = 3.0      # window bottom, below the board's top surface
LED_WINDOW_ABOVE = 8.0      # window top, above the board's top surface

# Receiver (TSOP38238 on its flying lead): hole in the lid, over the LED-side gap
# near the antenna end. Press the dome into it and fix with a dab of hot glue.
TSOP_HOLE_D = 5.5
TSOP_FROM_ANTENNA_WALL = 15.0

MIN_CLEARANCE = 1.0         # smallest gap allowed between separate features


# --------------------------------------------------------------------------
# Layout: every position as plain numbers, checked before any solid is built
# --------------------------------------------------------------------------

def board_hole(col: int, row: int) -> tuple[float, float]:
    """Grid hole position relative to the board's row-1 / column-A corner.

    Assumes the hole grid is centred on the board, as on the boards measured
    for tools/perfboard.py.
    """
    x = (BOARD_W - (COLS - 1) * PITCH) / 2 + (col - 1) * PITCH
    y = (BOARD_L - (ROWS - 1) * PITCH) / 2 + (row - 1) * PITCH
    return x, y


@dataclass(frozen=True)
class Layout:
    inner_w: float
    inner_l: float
    inner_h: float                          # floor top to lid underside
    board_x0: float                         # board's column-A edge
    board_y0: float                         # board's row-1 edge
    board_top_z: float
    standoffs: tuple[tuple[float, float], ...]
    lid_bosses: tuple[tuple[float, float], ...]
    usb_centre: tuple[float, float]         # (x, z)
    led_window: tuple[float, float, float, float]   # (y centre, width, z bottom, z top)
    tsop: tuple[float, float]

    @property
    def outer_w(self) -> float:
        return self.inner_w + 2 * WALL

    @property
    def outer_l(self) -> float:
        return self.inner_l + 2 * WALL

    @property
    def base_h(self) -> float:
        return FLOOR + self.inner_h


def make_layout() -> Layout:
    inner_w = GAP_LEFT + BOARD_W + GAP_RIGHT
    inner_l = GAP_END + BOARD_L + GAP_END
    board_x0, board_y0 = -inner_w / 2 + GAP_LEFT, -inner_l / 2 + GAP_END
    board_top_z = FLOOR + STANDOFF_H + BOARD_T

    usb_x = board_x0 + (board_hole(1, 1)[0] + board_hole(11, 1)[0]) / 2
    usb_z = board_top_z + USB_Z_ABOVE_BOARD
    # Lid height: clear the tallest part, and leave at least one wall's worth of
    # plastic above the USB slot so the slot is not an open notch.
    inner_top_z = max(board_top_z + TALLEST_ABOVE_BOARD + TOP_CLEARANCE,
                      usb_z + USB_SLOT_H / 2 + WALL)

    mx, my = (BOARD_W - MOUNT_PITCH_W) / 2, (BOARD_L - MOUNT_PITCH_L) / 2
    standoffs = tuple((board_x0 + x, board_y0 + y)
                      for x in (mx, BOARD_W - mx) for y in (my, BOARD_L - my))

    boss_r = LID_BOSS_D / 2
    bx, by = inner_w / 2 - boss_r + BOSS_OVERLAP, inner_l / 2 - boss_r + BOSS_OVERLAP
    lid_bosses = tuple((sx * bx, sy * by) for sx in (-1, 1) for sy in (-1, 1))

    led_ys = [board_y0 + board_hole(COLS, row)[1] for row in LED_ROWS]
    led_window = ((min(led_ys) + max(led_ys)) / 2,
                  max(led_ys) - min(led_ys) + LED_D + 2 * LED_WINDOW_MARGIN,
                  board_top_z - LED_WINDOW_BELOW,
                  board_top_z + LED_WINDOW_ABOVE)

    tsop = (board_x0 + BOARD_W + GAP_RIGHT / 2, inner_l / 2 - TSOP_FROM_ANTENNA_WALL)

    return Layout(inner_w, inner_l, inner_top_z - FLOOR, board_x0, board_y0, board_top_z,
                  standoffs, lid_bosses, (usb_x, usb_z), led_window, tsop)


def check_layout(lay: Layout) -> list[str]:
    """Return clashes and printability problems; empty means the layout is sound."""
    errors: list[str] = []
    so_r, boss_r = STANDOFF_D / 2, LID_BOSS_D / 2

    for s in lay.standoffs:
        for b in lay.lid_bosses:
            gap = math.dist(s, b) - so_r - boss_r
            if gap < MIN_CLEARANCE:
                errors.append(f"standoff {s} is {gap:.2f} mm from lid boss {b}")
    for b in lay.lid_bosses:
        # Board edges facing the boss: the long side on the boss's side.
        edge_x = lay.board_x0 if b[0] < 0 else lay.board_x0 + BOARD_W
        gap = abs(b[0] - edge_x) - boss_r
        if gap < MIN_CLEARANCE:
            errors.append(f"lid boss {b} is {gap:.2f} mm from the board edge")

    pilot_wall = (STANDOFF_D - STANDOFF_PILOT_D) / 2
    if pilot_wall < 1.2:
        errors.append(f"standoff wall around the pilot is only {pilot_wall:.2f} mm")
    if (LID_BOSS_D - LID_PILOT_D) / 2 < 1.2:
        errors.append("lid boss wall around the pilot is under 1.2 mm")
    if LID_PILOT_DEPTH > lay.inner_h:
        errors.append("lid pilot is deeper than the boss")

    usb_top = lay.usb_centre[1] + USB_SLOT_H / 2
    if usb_top > FLOOR + lay.inner_h - WALL + 1e-6:
        errors.append("less than one wall thickness above the USB slot")
    _, win_w, win_bottom, win_top = lay.led_window
    if win_bottom < FLOOR + MIN_CLEARANCE or win_top > FLOOR + lay.inner_h - WALL:
        errors.append("LED window runs into the floor or the top of the wall")
    if win_w / 2 > lay.inner_l / 2 - LID_BOSS_D - MIN_CLEARANCE:
        errors.append("LED window reaches the corner bosses")

    tx, ty = lay.tsop
    for b in lay.lid_bosses:
        if math.dist((tx, ty), b) < boss_r + TSOP_HOLE_D / 2 + MIN_CLEARANCE:
            errors.append(f"receiver hole clashes with lid boss {b}")
    return errors


# --------------------------------------------------------------------------
# Solids
# --------------------------------------------------------------------------

def _rounded_slab(w: float, l: float, r: float, h: float) -> Part:
    return extrude(RectangleRounded(w, l, r), amount=h)


def _post(d: float, h: float) -> Part:
    return Cylinder(d / 2, h, align=(Align.CENTER, Align.CENTER, Align.MIN))


def build_base(lay: Layout) -> Part:
    base = _rounded_slab(lay.outer_w, lay.outer_l, CORNER_R, lay.base_h)
    base -= Pos(0, 0, FLOOR) * _rounded_slab(lay.inner_w, lay.inner_l,
                                             CORNER_R - WALL, lay.inner_h + 1)

    for x, y in lay.standoffs:
        base += Pos(x, y, FLOOR) * _post(STANDOFF_D, STANDOFF_H)
        # Rib to the nearest end wall, sunk BOSS_OVERLAP into it.
        wall_y = math.copysign(lay.inner_l / 2 + BOSS_OVERLAP, y)
        rib_l = abs(wall_y - y)
        base += Pos(x, (y + wall_y) / 2, FLOOR) * Box(
            STANDOFF_RIB_W, rib_l, STANDOFF_H, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # Pilot stops at the floor so the underside stays closed.
        base -= Pos(x, y, FLOOR) * _post(STANDOFF_PILOT_D, STANDOFF_H + 1)

    for x, y in lay.lid_bosses:
        base += Pos(x, y, FLOOR) * _post(LID_BOSS_D, lay.inner_h)
        base -= Pos(x, y, lay.base_h - LID_PILOT_DEPTH) * _post(LID_PILOT_D,
                                                               LID_PILOT_DEPTH + 1)

    through = 2 * WALL + 2
    usb_x, usb_z = lay.usb_centre
    base -= Pos(usb_x, -lay.inner_l / 2 - WALL / 2, usb_z) * Box(
        USB_SLOT_W, through, USB_SLOT_H)

    win_y, win_w, win_bottom, win_top = lay.led_window
    base -= Pos(lay.inner_w / 2 + WALL / 2, win_y, (win_bottom + win_top) / 2) * Box(
        through, win_w, win_top - win_bottom)
    return base


def build_lid(lay: Layout) -> Part:
    """Lid in its closed position, sitting on top of the base."""
    z0 = lay.base_h
    lid = Pos(0, 0, z0) * _rounded_slab(lay.outer_w, lay.outer_l, CORNER_R, LID_T)
    for x, y in lay.lid_bosses:
        lid -= Pos(x, y, z0 - 1) * _post(LID_HOLE_D, LID_T + 2)
    tx, ty = lay.tsop
    lid -= Pos(tx, ty, z0 - 1) * _post(TSOP_HOLE_D, LID_T + 2)
    return lid


def build_fit_test(base: Part, lay: Layout) -> Part:
    """Floor, standoffs and the lowest few mm of wall: a quick hole-alignment print."""
    h = FLOOR + STANDOFF_H + 1.5
    keep = Box(lay.outer_w + 2, lay.outer_l + 2, h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return base & keep


def build_reference(lay: Layout) -> list[Part]:
    """Rough stand-ins for the board, ESP32 and LEDs, for the viewer only."""
    x0, y0 = lay.board_x0, lay.board_y0
    board = Pos(x0 + BOARD_W / 2, y0 + BOARD_L / 2, lay.board_top_z - BOARD_T) * Box(
        BOARD_W, BOARD_L, BOARD_T, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for x, y in lay.standoffs:
        board -= Pos(x, y, lay.board_top_z - BOARD_T - 1) * _post(MOUNT_HOLE_D, BOARD_T + 2)

    # DOIT DevKit V1: 28 x 51.6 mm, starting 1.7 pitches before row 1 (tools/perfboard.py).
    esp_cx = lay.usb_centre[0]
    esp_y0 = y0 + board_hole(1, 1)[1] - 1.7 * PITCH
    esp_z0 = lay.board_top_z + 8.5 + 2.5
    esp32 = Pos(esp_cx, esp_y0 + 51.6 / 2, esp_z0) * Box(
        28.0, 51.6, TALLEST_ABOVE_BOARD - 11.0, align=(Align.CENTER, Align.CENTER, Align.MIN))

    leds = []
    edge_x = x0 + BOARD_W
    for rows in (LED_ROWS[:2], LED_ROWS[2:]):
        y = y0 + sum(board_hole(COLS, r)[1] for r in rows) / 2
        leds.append(Pos(edge_x + 4.5, y, lay.board_top_z + LED_D / 2) * Cylinder(
            LED_D / 2, 8.6, rotation=(0, 90, 0)))
    return [board, esp32, *leds]


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def export(base: Part, lid: Part, fit_test: Part, lay: Layout, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    # The lid is modelled closed; print it flat on the bed, top face down.
    lid_print = Pos(0, 0, -lay.base_h) * lid
    paths = {
        "base.stl": base,
        "lid.stl": lid_print,
        "fit_test.stl": fit_test,
    }
    written = []
    for name, part in paths.items():
        path = out_dir / name
        if not export_stl(part, str(path)):
            raise RuntimeError(f"STL export failed: {path}")
        written.append(path)
    step = out_dir / "enclosure.step"
    if not export_step(Compound(children=[base, lid]), str(step)):
        raise RuntimeError(f"STEP export failed: {step}")
    written.append(step)
    return written


def preview(base: Part, lid: Part, reference: list[Part]) -> None:
    try:
        from ocp_vscode import show
    except ImportError:
        print("ocp_vscode not installed: skipping the viewer preview")
        return
    show(base, Pos(0, 0, 15) * lid, *reference,
         names=["base", "lid (lifted)", "board", "esp32", "led2", "led1"],
         colors=["steelblue", "lightsteelblue", "green", "black", "red", "red"],
         alphas=[0.6, 0.4, 1.0, 1.0, 1.0, 1.0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-show", action="store_true", help="skip the OCP CAD Viewer preview")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="output folder")
    args = parser.parse_args()

    lay = make_layout()
    errors = check_layout(lay)
    if errors:
        print("layout check FAILED:", *errors, sep="\n  ", file=sys.stderr)
        return 1

    base, lid = build_base(lay), build_lid(lay)
    fit_test = build_fit_test(base, lay)
    for name, part in (("base", base), ("lid", lid), ("fit_test", fit_test)):
        # is_valid is a method before build123d 0.10 and a property after.
        valid = part.is_valid() if callable(part.is_valid) else part.is_valid
        if not valid:
            print(f"{name} is not a valid solid", file=sys.stderr)
            return 1

    for path in export(base, lid, fit_test, lay, args.out):
        print(f"wrote {path}")
    print(f"outside {lay.outer_w:.1f} x {lay.outer_l:.1f} x {lay.base_h + LID_T:.1f} mm "
          f"(inside {lay.inner_w:.1f} x {lay.inner_l:.1f} x {lay.inner_h:.1f})")
    if not args.no_show:
        preview(base, lid, build_reference(lay))
    return 0


if __name__ == "__main__":
    sys.exit(main())
