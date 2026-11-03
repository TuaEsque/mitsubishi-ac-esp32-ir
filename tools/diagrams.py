#!/usr/bin/env python3
"""Generate the final-build diagrams for the Office AC project.

Outputs (SVG + PNG) go to docs/diagrams/:
  schematic      Schemdraw circuit: ESP32, transistor LED stage, TSOP38238
  system         Graphviz: Home Assistant <-> ESP32 <-> IR <-> MSZ-HR35VF
  wiring         Graphviz: point-to-point wiring, coloured by net, with the
                 breadboard line letters (A-G) used in the build notes
  build-status   Graphviz: build order, coloured by what is done / pending

Usage:
  pip install schemdraw graphviz      # plus the Graphviz `dot` binary
  python tools/diagrams.py            # writes all four
  python tools/diagrams.py --only schematic wiring

The circuit values live in CIRCUIT below, so a change (e.g. the 15 ohm
step-up) is made once and every diagram picks it up.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import graphviz
import schemdraw
import schemdraw.elements as elm

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "docs" / "diagrams"


@dataclass(frozen=True)
class Circuit:
    """Single source of truth for part values shown on the diagrams."""

    supply_v: float = 5.0          # VIN when USB powered (often ~4.7 V)
    led_vf: float = 1.3            # per 940 nm LED at ~65 mA
    vce_sat: float = 0.2
    led_r_ohm: float = 100.0       # each of the parallel LED resistors
    led_r_count: int = 3
    base_r_ohm: float = 470.0
    gpio_v: float = 3.3
    vbe: float = 0.7
    led_count: int = 2             # in series
    transistor: str = "2N2222A"

    @property
    def led_r_total(self) -> float:
        return self.led_r_ohm / self.led_r_count

    @property
    def led_ma(self) -> float:
        return self.led_ma_at(self.supply_v)

    def led_ma_at(self, supply_v: float) -> float:
        drop = supply_v - self.led_count * self.led_vf - self.vce_sat
        return 1000 * drop / self.led_r_total

    @property
    def base_ma(self) -> float:
        return 1000 * (self.gpio_v - self.vbe) / self.base_r_ohm

    @property
    def watts_per_led_r(self) -> float:
        i_each = self.led_ma / 1000 / self.led_r_count
        return i_each ** 2 * self.led_r_ohm


CIRCUIT = Circuit()

# Wire colours used on both the schematic notes and the wiring diagram.
NET_COLOURS = {
    "VIN": "#d62728",     # red
    "3V3": "#ff7f0e",     # orange
    "GND": "#222222",     # black
    "GPIO4": "#bcae00",   # yellow (darkened for contrast on white)
    "GPIO14": "#2ca02c",  # green
    "LED": "#1f77b4",     # blue: internal links on the LED stage
}


def _fmt_ohm(value: float) -> str:
    return f"{value:g} Ω"


# --------------------------------------------------------------------------
# Schematic (Schemdraw)
# --------------------------------------------------------------------------

def build_schematic(out_dir: Path) -> list[Path]:
    c = CIRCUIT
    d = schemdraw.Drawing(show=False)
    d.config(fontsize=11, bgcolor="white", unit=2.5, lw=1.4)

    # ESP32 as a block. Receiver pins on the left, LED-stage pins on the right,
    # so the two sub-circuits never cross. Pin labels give the DOIT silk name.
    esp = d.add(elm.Ic(
        size=(5.0, 6.0),
        pins=[
            elm.IcPin(name="3V3", side="left", pos=0.80, anchorname="p3v3", lblsize=10),
            elm.IcPin(name="D14 (GPIO14)", side="left", pos=0.50, anchorname="p14", lblsize=10),
            elm.IcPin(name="GND", side="left", pos=0.20, anchorname="gnd_l", lblsize=10),
            elm.IcPin(name="VIN (≈5 V)", side="right", pos=0.80, anchorname="vin", lblsize=10),
            elm.IcPin(name="D4 (GPIO4)", side="right", pos=0.50, anchorname="p4", lblsize=10),
            elm.IcPin(name="GND", side="right", pos=0.20, anchorname="gnd_r", lblsize=10),
        ],
    ).label("ESP32 DOIT DevKit V1\n(ESPHome)", loc="top", fontsize=11))

    # ---- LED stage --------------------------------------------------------
    d.add(elm.Line().at(esp.vin).right(1.0))
    node_a = d.here
    d.add(elm.Dot())

    # Parallel LED resistors, stacked upwards from the VIN row.
    row_gap = 1.3
    res_ends = []
    for i in range(c.led_r_count):
        y = node_a[1] + i * row_gap
        start = (node_a[0], y)
        if i > 0:
            d.add(elm.Line().at((node_a[0], y - row_gap)).to(start))
        # Labels must be attached before d.add() or they are not drawn.
        r = elm.Resistor().at(start).right(2.5).label(f"R{i + 1}", loc="bottom", fontsize=9)
        if i == c.led_r_count - 1:
            r.label(f"{c.led_r_count} × {_fmt_ohm(c.led_r_ohm)} in parallel "
                    f"≈ {c.led_r_total:.0f} Ω\n(¼ W parts, ≈{c.watts_per_led_r:.2f} W each)",
                    loc="top", fontsize=9)
        d.add(r)
        res_ends.append(r.end)
    for i in range(1, len(res_ends)):
        d.add(elm.Line().at(res_ends[i - 1]).to(res_ends[i]))
    node_b = res_ends[0]
    d.add(elm.Dot().at(node_b))

    d.add(elm.Line().at(node_b).right(2.5))
    led_top = d.here
    led1 = d.add(elm.LED().at(led_top).down(2.5)
                 .label("LED1\n940 nm", loc="bottom", fontsize=9))
    led2 = d.add(elm.LED().at(led1.end).down(2.5)
                 .label("LED2\n940 nm", loc="bottom", fontsize=9))
    d.add(elm.Label().at((led_top[0] + 1.6, led_top[1] - 0.6))
          .label(f"I ≈ {c.led_ma:.0f} mA\n(2 LEDs in series)", fontsize=9, color=NET_COLOURS["LED"]))

    q1 = d.add(elm.BjtNpn(circle=True).right().anchor("collector").at(led2.end)
               .label(f"Q1 {c.transistor}\nNPN", loc="right", fontsize=9))
    d.add(elm.Ground().at(q1.emitter))

    # Base drive from GPIO4.
    d.add(elm.Line().at(esp.p4).right(1.0))
    rb = d.add(elm.Resistor().right(2.5)
               .label(f"Rb {_fmt_ohm(c.base_r_ohm)}", fontsize=9)
               .label(f"I_b ≈ {c.base_ma:.1f} mA", loc="bottom", fontsize=9))
    d.add(elm.Wire("|-").at(rb.end).to(q1.base))

    d.add(elm.Line().at(esp.gnd_r).right(0.8))
    d.add(elm.Ground())

    # ---- Receiver ---------------------------------------------------------
    tsop = d.add(elm.Ic(
        size=(2.2, 3.0),
        pins=[
            elm.IcPin(name="VS", pin="3", side="right", pos=0.80, anchorname="vs", lblsize=10),
            elm.IcPin(name="OUT", pin="1", side="right", pos=0.50, anchorname="out", lblsize=10),
            elm.IcPin(name="GND", pin="2", side="right", pos=0.20, anchorname="gnd", lblsize=10),
        ],
        pinspacing=1.0,
    ).anchor("out").at((esp.p14[0] - 4.0, esp.p14[1]))
      .label("TSOP38238\n38 kHz IR receiver", loc="top", fontsize=9))

    # Jog each wire at a column between the two blocks so pins line up.
    jog_x = tsop.out[0] + 1.6
    d.add(elm.Line().at(esp.p14).to(tsop.out))
    for esp_pin, tsop_pin in ((esp.p3v3, tsop.vs), (esp.gnd_l, tsop.gnd)):
        d.add(elm.Line().at(esp_pin).to((jog_x, esp_pin[1])))
        d.add(elm.Line().at((jog_x, esp_pin[1])).to((jog_x, tsop_pin[1])))
        d.add(elm.Line().at((jog_x, tsop_pin[1])).to(tsop_pin))
    d.add(elm.Ground().at((jog_x, esp.gnd_l[1])))

    # ---- Notes ------------------------------------------------------------
    notes = (
        "Notes\n"
        "• TSOP38238 on 3V3, not 5 V: ESP32 inputs are not 5 V tolerant.\n"
        "  Pin order 1 OUT, 2 GND, 3 VS (dome facing you, legs down, left to right).\n"
        "• GPIO14 is configured inverted with the internal pull-up (office-ac.yaml).\n"
        "• All grounds are common. LED long leg (+) towards VIN.\n"
        "• Q1 2N2222A: flat face towards you, legs down, left to right E-B-C\n"
        "  (confirmed by diode test, 3 Nov 2026: base→C ≈ 0.70 V, B→E slightly higher).\n"
        f"• Currents assume VIN {c.supply_v:g} V, Vf {c.led_vf:g} V per LED; "
        f"at VIN 4.7 V expect ≈ {c.led_ma_at(4.7):.0f} mA.\n"
        "• Range step-up if needed: 15 Ω LED resistor, 220 Ω base, 100–470 µF across VIN–GND."
    )
    d.add(elm.Label().at((esp.gnd_l[0] - 4.5, esp.gnd_l[1] - 5.2))
          .label(notes, halign="left", valign="top", fontsize=9))

    return _save_schemdraw(d, out_dir / "schematic")


def _save_schemdraw(d: schemdraw.Drawing, stem: Path) -> list[Path]:
    paths = []
    for ext in ("svg", "png"):
        path = stem.with_suffix(f".{ext}")
        kwargs = {"dpi": 150} if ext == "png" else {}
        d.save(str(path), **kwargs)
        paths.append(path)
    return paths


# --------------------------------------------------------------------------
# Graphviz diagrams
# --------------------------------------------------------------------------

GRAPH_BASE = {
    "bgcolor": "white",
    "fontname": "Helvetica",
    "pad": "0.3",
    "nodesep": "0.4",
    "ranksep": "0.6",
}
NODE_BASE = {"fontname": "Helvetica", "fontsize": "11", "shape": "box",
             "style": "rounded,filled", "fillcolor": "#f5f5f5", "color": "#888888"}
EDGE_BASE = {"fontname": "Helvetica", "fontsize": "9", "color": "#555555"}


def _new_graph(name: str, rankdir: str = "LR") -> graphviz.Digraph:
    g = graphviz.Digraph(name, format="svg")
    g.attr(rankdir=rankdir, **GRAPH_BASE)
    g.attr("node", **NODE_BASE)
    g.attr("edge", **EDGE_BASE)
    return g


def _save_graphviz(g: graphviz.Digraph, stem: Path) -> list[Path]:
    paths = []
    for fmt in ("svg", "png"):
        g.format = fmt
        if fmt == "png":
            g.attr(dpi="150")
        rendered = g.render(filename=stem.name, directory=str(stem.parent), cleanup=True)
        paths.append(Path(rendered))
    return paths


def build_system(out_dir: Path) -> list[Path]:
    g = _new_graph("system")
    g.attr(label="Office AC: how the pieces talk", labelloc="t", fontsize="16")

    with g.subgraph(name="cluster_ha") as ha:
        ha.attr(label="Home Assistant", style="rounded", color="#4a90d9")
        ha.node("climate", "climate.office_ac\nmode · set point 16–31 °C · fan")
        ha.node("diag", "Diagnostics\nWi-Fi signal · Uptime · Status\nFirmware · Restart")

    with g.subgraph(name="cluster_box") as box:
        box.attr(label="Controller box (ESP32 + IR)", style="rounded", color="#2ca02c")
        box.node("esp", "ESP32 'office-ac'\nESPHome 2026.10.1\nfixed IP (DHCP reservation)",
                 fillcolor="#e8f5e9")
        box.node("ledstage", "LED stage\nQ1 2N2222 + 2 × 940 nm LED\n≈65 mA",
                 fillcolor="#fff8e1")
        box.node("tsop", "TSOP38238\nreceiver", fillcolor="#fff8e1")

    g.node("ac", "Mitsubishi Electric\nMSZ-HR35VF", shape="box3d", fillcolor="#e3f2fd")
    g.node("remote", "Real remote", shape="box3d", fillcolor="#e3f2fd")

    g.edge("climate", "esp", label="native API :6053\nencrypted, 2.4 GHz Wi-Fi", dir="both")
    g.edge("diag", "esp", dir="back", style="dashed")
    g.edge("esp", "ledstage", label="GPIO4\n38 kHz carrier")
    g.edge("ledstage", "ac", label="IR: 18-byte frame ×2\n(whole state + checksum)",
           color="#d62728", fontcolor="#d62728")
    g.edge("remote", "tsop", label="IR presses", color="#d62728", fontcolor="#d62728")
    g.edge("remote", "ac", style="dotted", color="#d62728")
    g.edge("tsop", "esp", label="GPIO14\ndemodulated")

    g.node("note", "IR is one-way: the entity shows what was last sent or seen,\n"
                   "not the unit's real state (timers, presses aimed away).",
           shape="note", fillcolor="#fffde7", fontsize="9")
    g.edge("climate", "note", style="invis")
    return _save_graphviz(g, out_dir / "system")


def _part(title: str, rows: list[tuple[str, str]], fill: str = "#fafafa") -> str:
    """HTML-table node label: a title row, then one row per (port, text) pin."""
    cells = "".join(
        f'<TR><TD PORT="{port}" ALIGN="LEFT">{text}</TD></TR>' for port, text in rows
    )
    return (f'<<TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" '
            f'BGCOLOR="{fill}"><TR><TD BGCOLOR="#e0e0e0"><B>{title}</B></TD></TR>{cells}</TABLE>>')


def build_wiring(out_dir: Path) -> list[Path]:
    """Point-to-point wiring; edge labels are the breadboard lines A-G.

    Laid out left to right: receiver | ESP32 | LED stage, so wires never cross
    the board. Each wire leaves its pin on the side facing its destination.
    """
    c = CIRCUIT
    g = _new_graph("wiring")
    g.attr(label="Wiring: every connection, coloured by net (letters = breadboard lines)",
           labelloc="t", fontsize="16", splines="spline", nodesep="0.5", ranksep="1.0")
    g.attr("node", shape="plaintext", style="")

    g.node("tsop", _part("TSOP38238 (dome towards you)",
                         [("vs", "3  VS"), ("out", "1  OUT"), ("gnd", "2  GND")], "#fff8e1"))

    # Two columns: receiver pins on the left edge, LED-stage pins on the right.
    # Row/pin positions are for the DOIT 30-pin board, counted from the USB end.
    esp_label = (
        '<<TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" BGCOLOR="#e8f5e9">'
        '<TR><TD COLSPAN="2" BGCOLOR="#c8e6c9"><B>ESP32 DOIT DevKit V1</B></TD></TR>'
        '<TR><TD PORT="v33" ALIGN="LEFT">3V3  (3V3 row, pin 1)</TD>'
        '<TD PORT="vin" ALIGN="RIGHT">VIN  (VIN row, pin 1)</TD></TR>'
        '<TR><TD PORT="d14" ALIGN="LEFT">D14  (VIN row, pin 5)</TD>'
        '<TD PORT="d4" ALIGN="RIGHT">D4  (3V3 row, pin 5)</TD></TR>'
        '<TR><TD PORT="gnd1" ALIGN="LEFT">GND  (3V3 row, pin 2)</TD>'
        '<TD PORT="gnd2" ALIGN="RIGHT">GND  (VIN row, pin 2)</TD></TR>'
        '</TABLE>>'
    )
    g.node("esp", esp_label)

    g.node("res", _part(f"{c.led_r_count} × {_fmt_ohm(c.led_r_ohm)} in parallel "
                        f"≈ {c.led_r_total:.0f} Ω",
                        [("a", "all left ends"), ("b", "all right ends")]))
    g.node("rb", _part(f"Rb {_fmt_ohm(c.base_r_ohm)}", [("a", "end"), ("b", "end")]))
    g.node("led1", _part("LED1 940 nm", [("p", "+ long leg"), ("n", "− short leg")]))
    g.node("led2", _part("LED2 940 nm", [("p", "+ long leg"), ("n", "− short leg")]))
    g.node("q1", _part(f"Q1 {c.transistor} (NPN, flat face towards you)",
                       [("c", "C  collector (right leg)"), ("b", "B  base (middle leg)"),
                        ("e", "E  emitter (left leg)")]))

    def wire(a: str, b: str, net: str, line: str = "", **attrs: str) -> None:
        colour = NET_COLOURS[net]
        g.edge(a, b, label=f"{line}  {net}" if line else net, color=colour,
               fontcolor=colour, penwidth="2.2", arrowhead="none", **attrs)

    # Receiver side (left of the board).
    wire("tsop:vs:e", "esp:v33:w", "3V3")
    wire("tsop:out:e", "esp:d14:w", "GPIO14")
    wire("tsop:gnd:e", "esp:gnd1:w", "GND")

    # LED stage (right of the board), lines A-G as built on the breadboard.
    wire("esp:vin:e", "res:a:w", "VIN", "A")
    wire("res:b:e", "led1:p:w", "LED", "B")
    wire("led1:n:e", "led2:p:w", "LED", "C")
    wire("led2:n:e", "q1:c:w", "LED", "D")
    wire("esp:d4:e", "rb:a:w", "GPIO4", "F")
    wire("rb:b:e", "q1:b:w", "GPIO4", "E")
    wire("esp:gnd2:e", "q1:e:w", "GND", "G")

    g.attr("node", shape="note", style="filled", fillcolor="#fffde7", fontsize="9")
    with g.subgraph() as notes:
        notes.attr(rank="sink")
        notes.node("pins", "Pin positions are for the DOIT 30-pin board,\n"
                           "counted from the USB end. Clones vary:\n"
                           "read the silk-screen labels.")
        notes.node("checks", "Before power-up (multimeter):\n"
                             f"• A–B ≈ {c.led_r_total:.0f} Ω (50 Ω = one resistor unseated,"
                             " 100 Ω = two)\n"
                             "• no continuity VIN–GND or 3V3–GND\n"
                             "• D4 goes only to Rb\n"
                             "• Q1 E-B-C left to right: left → G, middle → E, right → D\n"
                             "• both LEDs: long leg towards VIN")
    g.edge("esp", "pins", style="invis")
    g.edge("q1", "checks", style="invis")
    return _save_graphviz(g, out_dir / "wiring")


# Build steps: (id, text, status). Status drives colour.
BUILD_STEPS = [
    ("esphome", "Install ESPHome add-on,\nsecrets, USB flash", "done"),
    ("ha", "Add 'Office AC' device\nin Home Assistant", "done"),
    ("rx", "Receiver test:\nremote updates the card", "done"),
    ("fan", "set_fan_mode: 4levels\nvertical_default: auto", "done"),
    ("direct", "Direct-drive LED test\nAC responds at ~40 cm", "done"),
    ("cleanup", "Old rest_command package\nremoved from HA", "done"),
    ("breadboard", "LED stage on breadboard\n(3 × 100 Ω, 2 LEDs, Rb)", "done"),
    ("transistor", "2N2222A arrived:\nE-B-C confirmed (diode test)", "done"),
    ("fit", "Fit Q1, recheck 33 Ω,\nloopback test", "next"),
    ("range", "Range test at the AC\n(goal: the whole room)", "todo"),
    ("stepup", "Step-up if short:\n15 Ω, 220 Ω base, bulk cap", "optional"),
    ("dump", "Comment out dump: all,\ninstall wirelessly", "todo"),
    ("layout", "Perfboard layout\n(leg order, row spacing, USB end)", "todo"),
    ("solder", "Solder: headers first,\ncontinuity checks", "todo"),
    ("box", "Enclosure: 2 LED holes → AC,\nreceiver hole → room, USB slot", "todo"),
]
STATUS_STYLE = {
    "done": {"fillcolor": "#c8e6c9", "color": "#2e7d32"},
    "next": {"fillcolor": "#ffe0b2", "color": "#e65100", "penwidth": "2"},
    "todo": {"fillcolor": "#eeeeee", "color": "#757575"},
    "optional": {"fillcolor": "#ffffff", "color": "#757575", "style": "rounded,dashed,filled"},
}


def build_status(out_dir: Path) -> list[Path]:
    g = _new_graph("build-status", rankdir="TB")
    g.attr(label="Build order (status 3 Nov 2026)", labelloc="t", fontsize="16")

    ids = [step_id for step_id, _, status in BUILD_STEPS if status != "optional"]
    for step_id, text, status in BUILD_STEPS:
        g.node(step_id, text, **STATUS_STYLE[status])
    for a, b in zip(ids, ids[1:]):
        g.edge(a, b)
    g.edge("range", "stepup", label="short of room", style="dashed")
    g.edge("stepup", "range", label="retest", style="dashed")

    with g.subgraph(name="cluster_key") as key:
        key.attr(label="Key", style="rounded", color="#bbbbbb", fontsize="10")
        for status in STATUS_STYLE:
            key.node(f"key_{status}", status, fontsize="9", **STATUS_STYLE[status])
    return _save_graphviz(g, out_dir / "build-status")


BUILDERS = {
    "schematic": build_schematic,
    "system": build_system,
    "wiring": build_wiring,
    "build-status": build_status,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--only", nargs="+", choices=sorted(BUILDERS))
    args = parser.parse_args(argv)

    if shutil.which("dot") is None:
        print("error: Graphviz `dot` not found. Install it (apt install graphviz, "
              "brew install graphviz, or graphviz.org/download).", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    for name in args.only or BUILDERS:
        for path in BUILDERS[name](args.out):
            print(f"wrote {path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
