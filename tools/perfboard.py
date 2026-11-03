#!/usr/bin/env python3
"""Perfboard layout for the Office AC box: layout data, a netlist check, a drawing.

The layout is data: the holes each part's legs go in, the bare-wire traces and
the insulated links on the solder side. analyse() rebuilds the circuit from that
data and compares it with the schematic's nets, so a moved part that would short
or open a net fails loudly instead of ending up in the drawing.

Coordinates: columns A-R (18) across the 5 x 7 cm board, rows 1-24 along it,
row 1 at the USB end. Seen from the component side with the USB end towards
you, column A is on the left.

Usage:
  python tools/perfboard.py            # netlist check only
  python tools/diagrams.py --only perfboard
"""

from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import patches  # noqa: E402
from matplotlib.collections import PatchCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

COLS = 18
ROWS = 24
KEEP_ROWS = 16          # rows 17-24 can be cut off
COL_LETTERS = "ABCDEFGHIJKLMNOPQR"
STRIP_FIRST_COL = 12    # column L: first column clear of the ESP32


# --------------------------------------------------------------------------
# Layout data
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Part:
    ref: str
    kind: str                         # socket | resistor | to92 | led | lead
    pins: dict[str, str] = field(hash=False)   # pin name -> hole, e.g. {"E": "O3"}
    label: str = ""


@dataclass(frozen=True)
class Link:
    """Insulated wire on the solder side; may cross other pads."""

    ref: str
    a: str
    b: str


@dataclass(frozen=True)
class Net:
    name: str
    colour_key: str                   # key into the wiring diagram's NET_COLOURS
    members: frozenset[str]           # "REF.pin"


# DOIT DevKit V1 30-pin, counted from the USB end.
ESP_VIN_ROW = ("VIN", "GND1", "D13", "D12", "D14", "D27", "D26", "D25",
               "D33", "D32", "D35", "D34", "VN", "VP", "EN")
ESP_3V3_ROW = ("3V3", "GND2", "D15", "D2", "D4", "RX2", "TX2", "D5",
               "D18", "D19", "D21", "RX0", "TX0", "D22", "D23")


def _esp32_pins() -> dict[str, str]:
    pins = {name: f"A{i}" for i, name in enumerate(ESP_VIN_ROW, start=1)}
    pins.update({name: f"K{i}" for i, name in enumerate(ESP_3V3_ROW, start=1)})
    return pins


PARTS: tuple[Part, ...] = (
    Part("U1", "socket", _esp32_pins(), "ESP32 DOIT in sockets"),
    Part("R1", "resistor", {"1": "M11", "2": "Q11"}, "100 Ω"),
    Part("R2", "resistor", {"1": "M13", "2": "Q13"}, "100 Ω"),
    Part("R3", "resistor", {"1": "M15", "2": "Q15"}, "100 Ω"),
    Part("R4", "resistor", {"1": "L5", "2": "P5"}, "470 Ω"),
    # Flat face towards the USB end: E-B-C left to right, as diode-tested.
    Part("Q1", "to92", {"E": "O3", "B": "P3", "C": "Q3"}, "2N2222A"),
    Part("LED2", "led", {"A": "R8", "K": "R7"}),
    Part("LED1", "led", {"A": "R11", "K": "R10"}),
    Part("J1", "lead", {"VS": "L1", "GND": "M2", "OUT": "M4"}, "TSOP38238 flying lead"),
)

# Bare tinned wire (part legs or resistor offcuts) on the solder side,
# soldered at every pad it crosses. Each step is to a neighbouring pad.
TRACES: tuple[tuple[str, ...], ...] = (
    ("K1", "L1"),                                   # 3V3 -> TSOP VS
    ("K2", "L2", "M2", "N2", "O2", "O3"),           # GND -> TSOP GND, Q1 E
    ("K5", "L5"),                                   # D4 -> R4
    ("A1", "B1"),                                   # VIN -> W1
    ("A5", "B5"),                                   # D14 -> W2
    ("M4", "N4"),                                   # TSOP OUT -> W2
    ("P3", "P4", "P5"),                             # Q1 B -> R4
    ("Q3", "R3", "R4", "R5", "R6", "R7"),           # Q1 C -> LED2 -
    ("R8", "R9", "R10"),                            # LED2 + -> LED1 -
    ("R11", "Q11", "Q12", "Q13", "Q14", "Q15"),     # LED1 + -> R1-R3
    ("M11", "M12", "M13", "M14", "M15"),            # VIN bus -> R1-R3
)

LINKS: tuple[Link, ...] = (
    Link("W1", "B1", "M12"),                        # VIN across to the strip
    Link("W2", "B5", "N4"),                         # D14 across to the strip
)

NETS: tuple[Net, ...] = (
    Net("VIN", "VIN", frozenset({"U1.VIN", "R1.1", "R2.1", "R3.1"})),
    Net("LED+", "LED", frozenset({"R1.2", "R2.2", "R3.2", "LED1.A"})),
    Net("LED1-LED2", "LED", frozenset({"LED1.K", "LED2.A"})),
    Net("Collector", "LED", frozenset({"LED2.K", "Q1.C"})),
    Net("Base", "GPIO4", frozenset({"R4.2", "Q1.B"})),
    Net("GPIO4", "GPIO4", frozenset({"U1.D4", "R4.1"})),
    Net("GND", "GND", frozenset({"U1.GND2", "Q1.E", "J1.GND"})),
    Net("3V3", "3V3", frozenset({"U1.3V3", "J1.VS"})),
    Net("GPIO14", "GPIO14", frozenset({"U1.D14", "J1.OUT"})),
)


# --------------------------------------------------------------------------
# Netlist check
# --------------------------------------------------------------------------

def hole_xy(hole: str) -> tuple[int, int]:
    """'M13' -> (13, 13). Raises ValueError for a hole that is not on the board."""
    letter, digits = hole[:1], hole[1:]
    if letter not in COL_LETTERS or not digits.isdigit() or not 1 <= int(digits) <= ROWS:
        raise ValueError(f"not a hole on the {COLS} x {ROWS} board: {hole!r}")
    return COL_LETTERS.index(letter) + 1, int(digits)


@dataclass
class Analysis:
    errors: list[str]
    hole_net: dict[str, Net]          # every hole that ends up on a net


def analyse(parts=PARTS, traces=TRACES, links=LINKS, nets=NETS) -> Analysis:
    errors: list[str] = []
    occupant: dict[str, str] = {}
    pin_hole: dict[str, str] = {}

    def occupy(hole: str, who: str) -> None:
        hole_xy(hole)
        if hole in occupant:
            errors.append(f"hole {hole} used by both {occupant[hole]} and {who}")
        occupant[hole] = who

    for part in parts:
        for pin, hole in part.pins.items():
            who = f"{part.ref}.{pin}"
            occupy(hole, who)
            pin_hole[who] = hole
            col, _ = hole_xy(hole)
            if part.kind != "socket" and col < STRIP_FIRST_COL:
                errors.append(f"{who} in {hole} is under the ESP32")
    for link in links:
        occupy(link.a, f"{link.ref} end")
        occupy(link.b, f"{link.ref} end")

    parent: dict[str, str] = {}

    def find(h: str) -> str:
        parent.setdefault(h, h)
        while parent[h] != h:
            parent[h] = parent[parent[h]]
            h = parent[h]
        return h

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    for trace in traces:
        for a, b in zip(trace, trace[1:]):
            (ca, ra), (cb, rb) = hole_xy(a), hole_xy(b)
            if abs(ca - cb) + abs(ra - rb) != 1:
                errors.append(f"trace step {a} -> {b} is not between neighbouring pads")
            union(a, b)
    for link in links:
        union(link.a, link.b)

    groups: dict[str, set[str]] = defaultdict(set)
    for who, hole in pin_hole.items():
        groups[find(hole)].add(who)
    actual = {frozenset(g) for g in groups.values() if len(g) > 1}
    expected = {net.members: net for net in nets}
    for members, net in expected.items():
        if members not in actual:
            errors.append(f"net {net.name} is not exactly {sorted(members)}")
    for members in actual - expected.keys():
        errors.append(f"unexpected connection: {sorted(members)}")

    hole_net: dict[str, Net] = {}
    roots = {find(pin_hole[next(iter(net.members))]): net for net in nets}
    for hole in set(parent) | set(pin_hole.values()) | set(occupant):
        net = roots.get(find(hole))
        if net is not None:
            hole_net[hole] = net
    return Analysis(errors, hole_net)


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

BOARD_FILL = "#e3ecd9"
PAD_FILL = "#d2ae74"
PAD_EDGE = "#8a6d3b"
SOCKET_EDGE = "#222222"


def _pt(hole: str, mirror: bool) -> tuple[float, float]:
    col, row = hole_xy(hole)
    return (COLS + 1 - col if mirror else col), row


def _draw_board(ax, mirror: bool) -> None:
    ax.add_patch(patches.Rectangle((0.4, 0.4), COLS + 0.2, ROWS + 0.2,
                                   fc=BOARD_FILL, ec="#8fa680", lw=1.2, zorder=0))
    pads, holes = [], []
    for col in range(1, COLS + 1):
        for row in range(1, ROWS + 1):
            x = COLS + 1 - col if mirror else col
            pads.append(patches.Circle((x, row), 0.3))
            holes.append(patches.Circle((x, row), 0.1))
    ax.add_collection(PatchCollection(pads, fc=PAD_FILL, ec=PAD_EDGE, lw=0.4, zorder=1))
    ax.add_collection(PatchCollection(holes, fc="white", ec="none", zorder=1.1))

    for socket_col in ("A", "K"):
        for row in range(1, 16):
            x, y = _pt(f"{socket_col}{row}", mirror)
            ax.add_patch(patches.Rectangle((x - 0.36, y - 0.36), 0.72, 0.72, fill=False,
                                           ec=SOCKET_EDGE, lw=1.0, zorder=1.2))

    # Rows beyond KEEP_ROWS are optional: fade them and mark the cut.
    ax.add_patch(patches.Rectangle((0.4, KEEP_ROWS + 0.5), COLS + 0.2, ROWS - KEEP_ROWS + 0.1,
                                   fc="white", ec="none", alpha=0.6, zorder=1.5))
    ax.plot([0.1, COLS + 0.9], [KEEP_ROWS + 1] * 2, ls=(0, (6, 3)), color="#555", lw=1.2,
            zorder=1.6)
    ax.text((COLS + 1) / 2, KEEP_ROWS + 1.45,
            f"optional: cut along row {KEEP_ROWS + 1} (keeps rows 1–{KEEP_ROWS}, ≈ 50 × 43 mm)",
            ha="center", fontsize=8, color="#444", zorder=6.5,
            bbox=dict(fc="white", ec="none", alpha=0.9, pad=0.8))

    for i, letter in enumerate(COL_LETTERS, start=1):
        x = COLS + 1 - i if mirror else i
        for y in (-0.05, ROWS + 0.95):
            ax.text(x, y, letter, ha="center", va="center", fontsize=6.5, color="#555")
    row_x = -0.25 if mirror else -2.5
    for row in range(1, ROWS + 1):
        ax.text(row_x, row, str(row), ha="right", va="center", fontsize=6.5, color="#555")


def _socket_labels(ax, mirror: bool) -> None:
    used = {"VIN", "D14", "3V3", "GND2", "D4"}
    for names, col in ((ESP_VIN_ROW, "A"), (ESP_3V3_ROW, "K")):
        for row, name in enumerate(names, start=1):
            x, y = _pt(f"{col}{row}", mirror)
            if mirror:
                tx, ha = x + 0.5, "left"
            else:
                tx, ha = x - 0.5, "right"
            text = "GND" if name.startswith("GND") else name
            strong = name in used
            ax.text(tx, y, text, ha=ha, va="center", fontsize=6.5 if strong else 5.5,
                    fontweight="bold" if strong else "normal",
                    color="#111" if strong else "#888", zorder=6)


def _draw_traces(ax, analysis: Analysis, colours: dict[str, str], mirror: bool,
                 faint: bool) -> None:
    for trace in TRACES:
        net = analysis.hole_net[trace[0]]
        xs, ys = zip(*(_pt(h, mirror) for h in trace))
        ax.plot(xs, ys, color=colours[net.colour_key], lw=3.5 if faint else 6.5,
                alpha=0.3 if faint else 0.9, solid_capstyle="round", zorder=2)


def _draw_links(ax, analysis: Analysis, colours: dict[str, str], mirror: bool,
                faint: bool) -> None:
    for link in LINKS:
        net = analysis.hole_net[link.a]
        a, b = _pt(link.a, mirror), _pt(link.b, mirror)
        ax.add_patch(patches.FancyArrowPatch(
            a, b, arrowstyle="-", connectionstyle="arc3,rad=-0.12" if mirror else "arc3,rad=0.12",
            color=colours[net.colour_key], lw=2.6, ls=(0, (5, 2.5)),
            alpha=0.45 if faint else 1.0, zorder=2.5))
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        ax.text(mx, my + 0.55, f"{link.ref} insulated", ha="center", fontsize=6.5,
                color=colours[net.colour_key], alpha=0.6 if faint else 1.0, zorder=6,
                bbox=dict(fc="white", ec="none", alpha=0.7, pad=0.6))


def _draw_resistor(ax, part: Part) -> None:
    (x1, y1), (x2, y2) = (_pt(h, False) for h in part.pins.values())
    ax.plot([x1, x2], [y1, y2], color="#777", lw=1.6, zorder=4)
    span = abs(x2 - x1) + abs(y2 - y1)
    w, h = span * 0.58, 0.62
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    if x1 == x2:
        w, h = h, w
    fill = "#8fc0ec" if part.label.startswith("100") else "#ecdcb2"
    ax.add_patch(patches.FancyBboxPatch((cx - w / 2, cy - h / 2), w, h,
                                        boxstyle="round,pad=0.02,rounding_size=0.25",
                                        fc=fill, ec="#555", lw=0.8, zorder=5))
    ax.text(cx, cy, f"{part.ref} {part.label}", ha="center", va="center", fontsize=6.5,
            zorder=6)


def _draw_to92(ax, part: Part) -> None:
    """Legs in one row, flat face towards row 1 (the USB end)."""
    pts = [_pt(h, False) for h in part.pins.values()]
    xs, ys = zip(*pts)
    if len(set(ys)) != 1:
        raise ValueError(f"{part.ref}: drawing supports legs in one row only")
    y = ys[0]
    x0, x1 = min(xs) - 0.45, max(xs) + 0.45
    face_y = y - 0.45
    # Half-ellipse behind the flat face.
    t = np.linspace(0, np.pi, 40)
    cx, rx, ry = (x0 + x1) / 2, (x1 - x0) / 2, 1.35
    outline = [(x1, face_y)] + [(cx + rx * np.cos(a), face_y + ry * np.sin(a)) for a in t] \
        + [(x0, face_y)]
    ax.add_patch(patches.Polygon(outline, closed=True, fc="#3c3c3c", ec="#111", lw=0.8,
                                 zorder=5))
    for (px, py), pin in zip(pts, part.pins):
        ax.text(px, py + 0.25, pin, ha="center", va="center", fontsize=7, color="white",
                fontweight="bold", zorder=6)
    ax.text(cx + 0.6, face_y - 0.3, f"{part.ref} {part.label} · flat face → USB end",
            ha="center", va="top", fontsize=6.5, zorder=6,
            bbox=dict(fc="white", ec="none", alpha=0.8, pad=0.6))


def _draw_led(ax, part: Part) -> None:
    """LED lying flat, legs bent 90°, pointing out over the right-hand edge."""
    (xa, ya), (xk, yk) = _pt(part.pins["A"], False), _pt(part.pins["K"], False)
    edge = COLS + 0.55
    ymid = (ya + yk) / 2
    for (x, y) in ((xa, ya), (xk, yk)):
        ax.plot([x, edge + 0.05], [y, y], color="#777", lw=1.6, zorder=4)
    ax.add_patch(patches.Rectangle((edge, ymid - 1.12), 0.28, 2.24, fc="#b9d4ec",
                                   ec="#5a7fa0", lw=0.8, zorder=5))
    ax.add_patch(patches.Rectangle((edge + 0.28, ymid - 0.97), 1.9, 1.94, fc="#cfe3f5",
                                   ec="#5a7fa0", lw=0.8, zorder=5))
    ax.add_patch(patches.Wedge((edge + 2.18, ymid), 0.97, -90, 90, fc="#cfe3f5",
                               ec="#5a7fa0", lw=0.8, zorder=5))
    ax.text(edge + 1.4, ymid, part.ref, ha="center", va="center", fontsize=7, zorder=6)
    for (x, y), sign in (((xa, ya), "+"), ((xk, yk), "−")):
        dy = 0.38 if y == max(ya, yk) else -0.38
        ax.text(x + 0.3, y + dy, sign, ha="center", va="center", fontsize=8,
                fontweight="bold", zorder=6)
    ax.annotate("", xy=(edge + 4.1, ymid), xytext=(edge + 3.3, ymid),
                arrowprops=dict(arrowstyle="->", color="#c62828", lw=1.4), zorder=6)


def _draw_lead(ax, part: Part, analysis: Analysis, colours: dict[str, str]) -> None:
    """Flying lead to the TSOP38238: cut F-F jumpers, receiver plugs into the ends."""
    order = ("VS", "GND", "OUT")          # left to right on the drawing, no crossings
    base_x, base_y = 14.8, -2.9
    for i, pin in enumerate(order):
        end = (base_x + 1.15 * i, base_y)
        hole = part.pins[pin]
        colour = colours[analysis.hole_net[hole].colour_key]
        ax.add_patch(patches.FancyArrowPatch(end, _pt(hole, False), arrowstyle="-",
                                             connectionstyle="arc3,rad=-0.15",
                                             color=colour, lw=2.2, zorder=4.5))
        ax.text(end[0], end[1] - 0.45, pin, ha="center", va="top", fontsize=7,
                fontweight="bold", color=colour)
    ax.text(base_x + 1.15, base_y - 1.25,
            "J1: flying lead to the TSOP38238\n(cut F-F jumpers; receiver plugs in)\n"
            "TSOP, dome facing you: 1 OUT · 2 GND · 3 VS",
            ha="center", va="top", fontsize=6.5)


def _draw_esp32_outline(ax) -> None:
    ax.add_patch(patches.Rectangle((0.35, -0.7), 11.3, 20.3, fc="#1b1b1b", alpha=0.08,
                                   ec="#333", lw=1.3, ls=(0, (4, 2)), zorder=3))
    ax.add_patch(patches.Rectangle((0.35, 16.4), 11.3, 3.2, fill=False, hatch="///",
                                   ec="#999", lw=0.6, zorder=3))
    ax.text(6, 19.0, "Wi-Fi antenna end: keep clear", ha="center", va="center",
            fontsize=8, zorder=6, bbox=dict(fc="white", ec="none", alpha=0.85, pad=1))
    ax.text(6, 9.0, "ESP32 DOIT in sockets\n(outline approximate,\ndry-fit first)\n\n"
            "nothing under it on\nthe component side", ha="center", va="center",
            fontsize=8, color="#333", zorder=6,
            bbox=dict(fc="white", ec="none", alpha=0.75, pad=1.5))
    ax.add_patch(patches.Rectangle((4.4, -1.6), 3.2, 1.2, fc="#9e9e9e", ec="#555", zorder=4))
    ax.text(6, -1.0, "USB", ha="center", va="center", fontsize=7, color="white", zorder=5)


def _hole_label(part: Part, pin: str) -> str:
    if part.kind == "resistor":
        return part.ref
    if part.kind == "led":
        return f"{part.ref} {'+' if pin == 'A' else '−'}"
    if part.kind == "lead":
        return f"TSOP {pin}"
    return f"{part.ref} {pin}"


def _solder_side_labels(ax) -> None:
    for part in PARTS:
        if part.kind == "socket":
            continue
        for pin, hole in part.pins.items():
            x, y = _pt(hole, True)
            ax.text(x, y + 0.45, _hole_label(part, pin), ha="center", va="bottom",
                    fontsize=5.5, zorder=6,
                    bbox=dict(fc="white", ec="none", alpha=0.7, pad=0.3))
    for link in LINKS:
        for hole in (link.a, link.b):
            x, y = _pt(hole, True)
            ax.text(x + 0.42, y - 0.2, link.ref, ha="left", va="top", fontsize=5.5, zorder=6,
                    bbox=dict(fc="white", ec="none", alpha=0.7, pad=0.3))


def build(out_dir: Path, colours: dict[str, str]) -> list[Path]:
    analysis = analyse()
    if analysis.errors:
        raise ValueError("perfboard layout fails the netlist check:\n  "
                         + "\n  ".join(analysis.errors))

    fig, (top, bottom) = plt.subplots(1, 2, figsize=(19, 14.5),
                                      gridspec_kw={"width_ratios": [26.4, 23.0]})
    fig.suptitle("Perfboard layout: 5 × 7 cm proto board (18 × 24 holes), "
                 "row 1 at the USB end", fontsize=15)

    # Component side.
    _draw_board(top, mirror=False)
    _draw_traces(top, analysis, colours, mirror=False, faint=True)
    _draw_links(top, analysis, colours, mirror=False, faint=True)
    _draw_esp32_outline(top)
    _socket_labels(top, mirror=False)
    for part in PARTS:
        if part.kind == "resistor":
            _draw_resistor(top, part)
        elif part.kind == "to92":
            _draw_to92(top, part)
        elif part.kind == "led":
            _draw_led(top, part)
        elif part.kind == "lead":
            _draw_lead(top, part, analysis, colours)
    top.text(-3.0, -1.9,
             "• Column L: low parts only (the ESP32 board overhangs it).\n"
             "• LEDs: bend the legs 90° so they point out over the right edge,\n"
             "  angled ~10° apart. Long leg (+) in the upper hole.\n"
             "• Faint lines are the solder-side wiring, seen through the board.",
             ha="left", va="top", fontsize=7.5)
    top.set_title("Component side: parts on top, USB end towards you", fontsize=12)
    top.set_xlim(-3.2, 23.2)

    # Solder side, mirrored as it is when you turn the board over.
    _draw_board(bottom, mirror=True)
    _draw_traces(bottom, analysis, colours, mirror=True, faint=False)
    _draw_links(bottom, analysis, colours, mirror=True, faint=False)
    _socket_labels(bottom, mirror=True)
    _solder_side_labels(bottom)
    bottom.text(0.4, -1.9,
                f"Netlist check passed: {len(NETS)} nets rebuilt from this layout match "
                "the schematic (tools/perfboard.py).\n"
                "Solid lines: bare wire soldered at every pad it crosses. "
                "Dashed: insulated wire.",
                ha="left", va="top", fontsize=7.5)
    bottom.set_title("Solder side: board turned over (left and right swap)", fontsize=12)
    bottom.set_xlim(-1.2, 21.8)

    for ax in (top, bottom):
        ax.set_ylim(-5.6, ROWS + 1.6)
        ax.set_aspect("equal")
        ax.axis("off")

    used_keys = []
    for net in NETS:
        if net.colour_key not in used_keys:
            used_keys.append(net.colour_key)
    names = {"GPIO4": "GPIO4 / base", "LED": "LED string"}
    handles = [Line2D([], [], color=colours[k], lw=5, label=names.get(k, k)) for k in used_keys]
    handles += [Line2D([], [], color="#666", lw=4, label="bare wire (solder side)"),
                Line2D([], [], color="#666", lw=2.4, ls=(0, (5, 2.5)),
                       label="insulated wire (solder side)")]
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), fontsize=9,
               frameon=False)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))

    paths = []
    for ext in ("svg", "png"):
        path = out_dir / f"perfboard.{ext}"
        fig.savefig(path, dpi=150 if ext == "png" else None, facecolor="white")
        paths.append(path)
    plt.close(fig)
    return paths


def main() -> int:
    analysis = analyse()
    if analysis.errors:
        print("netlist check FAILED:", *analysis.errors, sep="\n  ", file=sys.stderr)
        return 1
    print(f"netlist check OK: {len(NETS)} nets match the schematic")
    return 0


if __name__ == "__main__":
    sys.exit(main())
