#!/usr/bin/env python3
"""analyse_ir.py - record, decode and forge raw IR captures from aircon remotes.

Works on the RAW lines printed by the `capture` firmware (mark/space timings in
microseconds, first value is the header mark). No third-party packages are
needed except `pyserial`, and only for `record --port`.

  record   save labelled button presses to a .jsonl file (from serial or stdin)
  decode   header / bit timings / bytes / checksum for every capture
  table    byte columns side by side, so you can see which ones change
  diff     exact bits that differ from a reference capture
  encode   forge a frame from bytes (fixing the checksum), print RAW + C array
  emit     print a recorded capture as a C array for IRsend::sendRaw()
  selftest synthetic round trip, no hardware needed

Bit conventions (shared by every command):
  * A "1" is a LONG space after the bit mark (use --invert if the protocol does
    it the other way round; Mitsubishi Heavy does).
  * Bits are packed LSB-first into bytes (use --msb for MSB-first). Mitsubishi
    Electric and Heavy are both LSB-first.
  * Bit numbers in `diff` are value bits: bit 0 = 0x01, bit 7 = 0x80.

Capture file formats (auto-detected): .jsonl as written by `record`, or a plain
serial log with `RAW,<n>,<t0>,<t1>,...` lines. In a plain log a `# text` line
labels the RAW line that follows it; `##` lines are ignored.
"""
import argparse
import json
import random
import sys
import time

GAP_US = 8000  # a space longer than this separates two frames in one capture


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def _parse_raw_line(line):
    parts = line.strip().split(",")
    try:
        n = int(parts[1])
        vals = [int(float(p)) for p in parts[2:] if p.strip() != ""]
    except (IndexError, ValueError):
        return None
    if len(vals) != n:
        print(f"warning: RAW line says {n} values but has {len(vals)}; using {len(vals)}",
              file=sys.stderr)
    return vals


class LogParser:
    """Incremental parser for the capture firmware's serial output.

    Recognised lines (everything else is ignored):
      # label: text   or   # text      label for the next RAW line
      ## text                           comment
      PROTO NAME bits=N overflow=NO     protocol the library guessed
      STATE 23CB26...                   decoded A/C state bytes, hex
      RAW,n,t0,t1,...                   the capture itself
    feed() returns a capture dict when it sees a RAW line, otherwise None.
    """

    def __init__(self):
        self.count = 0
        self._reset()

    def _reset(self):
        self.label, self.meta = None, {}

    def feed(self, line):
        line = line.strip()
        if not line or line.startswith("##"):
            return None
        if line.startswith("#"):
            text = line.lstrip("#").strip()
            if text.lower().startswith("label:"):
                text = text[6:].strip()
            if text:
                self.label = text
            return None
        if line.startswith("PROTO "):
            self.meta["protocol"] = line.split()[1] if len(line.split()) > 1 else "?"
            return None
        if line.startswith("STATE "):
            h = line.split(None, 1)[1].strip().replace(" ", "")
            if len(h) % 2 == 0:
                try:
                    self.meta["lib_bytes"] = [int(h[i:i + 2], 16) for i in range(0, len(h), 2)]
                except ValueError:
                    pass
            return None
        if line.startswith("RAW,"):
            vals = _parse_raw_line(line)
            cap = None
            if vals:
                cap = {"label": self.label or f"cap{self.count}", "timings": vals, "meta": self.meta}
                self.count += 1
            self._reset()
            return cap
        return None


def parse_log_lines(lines):
    """Turn serial-log lines into capture dicts."""
    parser, caps = LogParser(), []
    for line in lines:
        cap = parser.feed(line)
        if cap:
            caps.append(cap)
    return caps


def load_captures(path):
    if path == "-":
        text = sys.stdin.read().splitlines()
    else:
        with open(path, encoding="utf-8") as fh:
            text = fh.read().splitlines()
    nonblank = [t for t in text if t.strip()]
    if nonblank and nonblank[0].lstrip().startswith("{"):
        caps = []
        for t in nonblank:
            d = json.loads(t)
            d.setdefault("meta", {})
            caps.append(d)
        return caps
    return parse_log_lines(text)


def load_one(spec):
    """'file' or 'file:INDEX' -> (captures, index or None)."""
    idx = None
    if ":" in spec and not spec.endswith(":") and spec.rsplit(":", 1)[1].isdigit():
        spec, i = spec.rsplit(":", 1)
        idx = int(i)
    caps = load_captures(spec)
    if not caps:
        sys.exit(f"no captures found in {spec}")
    return caps, idx


# --------------------------------------------------------------------------
# frame analysis
# --------------------------------------------------------------------------
def split_frames(timings):
    """Split a capture into frames at long spaces. Returns [(frame, gap_before)]."""
    frames, cur, gap_before = [], [], None
    for i, t in enumerate(timings):
        if i % 2 == 1 and t > GAP_US:
            if cur:
                frames.append((cur, gap_before))
            cur, gap_before = [], t
        else:
            cur.append(t)
    if cur:
        frames.append((cur, gap_before))
    return frames


def _threshold(spaces):
    s = sorted(spaces)
    if len(s) < 2:
        return None
    jump, i = max((s[k + 1] - s[k], k) for k in range(len(s) - 1))
    lo, hi = s[i], s[i + 1]
    if hi < lo * 1.5:
        return None
    return (lo + hi) / 2


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0


def analyse_frame(frame, gap_before=None, msb=False, invert=False):
    """Decode one frame into a dict. Raises ValueError if it is too short."""
    if len(frame) < 5:
        raise ValueError("frame too short to contain a header and data")
    header = (frame[0], frame[1])
    body = frame[2:]
    footer = None
    if len(body) % 2 == 1:
        footer = body[-1]
        body = body[:-1]
    marks, spaces = body[0::2], body[1::2]
    thr = _threshold(spaces)
    longs = [s for s in spaces if thr is not None and s > thr]
    shorts = [s for s in spaces if thr is None or s <= thr]
    bits = [(1 if (thr is not None and s > thr) else 0) ^ (1 if invert else 0) for s in spaces]
    data = bits_to_bytes(bits, msb)
    return {
        "header": header, "bit_mark": _mean(marks), "short": _mean(shorts), "long": _mean(longs),
        "footer": footer, "gap_before": gap_before, "nbits": len(bits), "bytes": data,
        "threshold": thr,
    }


def bits_to_bytes(bits, msb=False):
    out = []
    for i in range(0, len(bits), 8):
        chunk = bits[i:i + 8]
        chunk = chunk + [0] * (8 - len(chunk))
        if msb:
            out.append(int("".join(map(str, chunk)), 2))
        else:
            out.append(sum(b << k for k, b in enumerate(chunk)))
    return out


def bytes_to_bits(data, msb=False):
    bits = []
    for v in data:
        order = range(7, -1, -1) if msb else range(8)
        bits += [(v >> k) & 1 for k in order]
    return bits


def checksum_report(b):
    """Describe any simple checksum the byte string seems to satisfy."""
    found = []
    if len(b) >= 2:
        if sum(b[:-1]) & 0xFF == b[-1]:
            found.append("sum8 (last byte = sum of the others, mod 256)")
        x = 0
        for v in b[:-1]:
            x ^= v
        if x == b[-1]:
            found.append("xor8 (last byte = xor of the others)")
    for off in range(1, len(b) - 3):
        tail = b[off:]
        if len(tail) % 2 == 0 and all(tail[i] ^ tail[i + 1] == 0xFF for i in range(0, len(tail), 2)):
            found.append(f"inverted byte pairs from byte {off}")
            break
    return found


def fix_checksum(b, kind):
    b = list(b)
    if kind == "sum8":
        b[-1] = sum(b[:-1]) & 0xFF
    elif kind == "xor8":
        x = 0
        for v in b[:-1]:
            x ^= v
        b[-1] = x
    elif kind != "none":
        sys.exit(f"unknown checksum kind {kind!r} (use sum8, xor8 or none)")
    return b


def hexs(b):
    return " ".join(f"{v:02X}" for v in b)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_decode(args):
    caps, only = load_one(args.file)
    for n, cap in enumerate(caps):
        if only is not None and n != only:
            continue
        frames = split_frames(cap["timings"])
        print(f"[{n}] {cap['label']}   ({len(cap['timings'])} timings, {len(frames)} frame(s))")
        first_bytes = None
        for k, (fr, gap) in enumerate(frames):
            try:
                a = analyse_frame(fr, gap, args.msb, args.invert)
            except ValueError as e:
                print(f"  frame {k + 1}: {e}")
                continue
            if first_bytes is not None and a["bytes"] == first_bytes:
                print(f"  frame {k + 1}: identical to frame 1 (gap before it: {gap} us)")
                continue
            print(f"  frame {k + 1}: header {a['header'][0]}/{a['header'][1]} us, "
                  f"bit mark ~{a['bit_mark']:.0f} us, short space ~{a['short']:.0f} us, "
                  f"long space ~{a['long']:.0f} us, footer mark {a['footer']} us"
                  + (f", gap before: {gap} us" if gap else ""))
            nb = a["nbits"]
            print(f"    {nb} bits = {nb // 8} bytes" + ("" if nb % 8 == 0 else f" + {nb % 8} bits (padded)"))
            print(f"    bytes: {hexs(a['bytes'])}")
            cs = checksum_report(a["bytes"])
            print(f"    checksum: {'; '.join(cs) if cs else 'no simple checksum found'}")
            if k == 0:
                first_bytes = a["bytes"]
                lib = cap.get("meta", {}).get("lib_bytes")
                if lib:
                    verdict = "MATCH" if lib == a["bytes"] else "MISMATCH"
                    print(f"    STATE line in log: {hexs(lib)}  -> {verdict}")
                    if verdict == "MISMATCH" and not args.invert:
                        print("    (if this is a Heavy Industries frame, try --invert)")


def _first_frame_bytes(cap, args):
    frames = split_frames(cap["timings"])
    k = min(args.frame, len(frames) - 1)
    return analyse_frame(frames[k][0], frames[k][1], args.msb, args.invert)["bytes"]


def cmd_table(args):
    caps, _ = load_one(args.file)
    rows = []
    for n, cap in enumerate(caps):
        try:
            rows.append((n, cap["label"], _first_frame_bytes(cap, args)))
        except ValueError as e:
            print(f"skipping [{n}]: {e}", file=sys.stderr)
    if not rows:
        sys.exit("nothing decodable")
    width = max(len(r[2]) for r in rows)
    lens = {len(r[2]) for r in rows}
    if len(lens) > 1:
        print(f"warning: captures have different lengths {sorted(lens)}; shorter ones are padded",
              file=sys.stderr)
    print("idx  " + " ".join(f"{i:02d}" for i in range(width)) + "  label")
    for n, label, b in rows:
        print(f"{n:>3}  " + " ".join(f"{v:02X}" for v in b) + "   " * (width - len(b)) + f"  {label}")
    vary = []
    for i in range(width):
        col = {r[2][i] for r in rows if i < len(r[2])}
        vary.append(len(col) > 1)
    print("     " + " ".join(" ^" if v else "  " for v in vary) + "  (^ = column changes)")


def cmd_diff(args):
    caps, _ = load_one(args.file)
    ref = _first_frame_bytes(caps[args.ref], args)
    print(f"reference [{args.ref}] {caps[args.ref]['label']}: {hexs(ref)}")
    for n, cap in enumerate(caps):
        if n == args.ref:
            continue
        try:
            b = _first_frame_bytes(cap, args)
        except ValueError as e:
            print(f"[{n}] {cap['label']}: {e}")
            continue
        print(f"[{n}] {cap['label']}: {hexs(b)}")
        changed = False
        for i in range(max(len(ref), len(b))):
            x = ref[i] if i < len(ref) else 0
            y = b[i] if i < len(b) else 0
            if x == y:
                continue
            changed = True
            flips = [f"bit {k}: {(x >> k) & 1}->{(y >> k) & 1}" for k in range(8) if ((x ^ y) >> k) & 1]
            print(f"    byte {i}: {x:02X} -> {y:02X}   ({', '.join(flips)})")
        if not changed:
            print("    identical")


def _c_array(vals, name="rawData"):
    lines = []
    for i in range(0, len(vals), 12):
        lines.append("  " + ", ".join(str(v) for v in vals[i:i + 12]))
    body = ",\n".join(lines)
    return (f"uint16_t {name}[{len(vals)}] = {{\n{body}}};  "
            f"// IRsend::sendRaw({name}, {len(vals)}, 38);")


def build_timings(params, data, msb, invert, frames=2):
    hm, hs = params["header"]
    seq = []
    bits = bytes_to_bits(data, msb)
    for f in range(frames):
        seq += [int(round(hm)), int(round(hs))]
        for b in bits:
            seq.append(int(round(params["bit_mark"])))
            seq.append(int(round(params["long"] if (b ^ (1 if invert else 0)) else params["short"])))
        seq.append(int(round(params["footer"] or params["bit_mark"])))
        if f != frames - 1:
            seq.append(int(round(params["gap"])))
    return seq


def cmd_encode(args):
    caps, idx = load_one(args.like)
    cap = caps[idx or 0]
    frames = split_frames(cap["timings"])
    a = analyse_frame(frames[0][0], frames[0][1], args.msb, args.invert)
    gap = frames[1][1] if len(frames) > 1 else (args.gap or 17000)
    params = {"header": a["header"], "bit_mark": a["bit_mark"], "short": a["short"],
              "long": a["long"], "footer": a["footer"], "gap": args.gap or gap}
    data = [int(x, 16) for x in args.bytes.replace(",", " ").split()]
    if len(data) * 8 != a["nbits"]:
        print(f"warning: {len(data)} bytes given but the capture has {a['nbits']} bits",
              file=sys.stderr)
    fixed = fix_checksum(data, args.fix_checksum)
    if fixed != data:
        print(f"checksum fixed: {hexs(data)} -> {hexs(fixed)}", file=sys.stderr)
    nframes = args.frames or len(frames)
    seq = build_timings(params, fixed, args.msb, args.invert, nframes)
    print(f"# bytes: {hexs(fixed)}   frames: {nframes}   timing source: {args.like}")
    print("RAW," + str(len(seq)) + "," + ",".join(map(str, seq)))
    print()
    print(_c_array(seq))


def cmd_emit(args):
    caps, idx = load_one(args.file)
    cap = caps[args.index if idx is None else idx]
    print(f"// {cap['label']}")
    print(_c_array(cap["timings"]))


def cmd_record(args):
    out = open(args.out, "a", encoding="utf-8")
    count = 0

    def save_cap(cap, label):
        nonlocal count
        out.write(json.dumps({"label": label, "timings": cap["timings"], "meta": cap["meta"],
                              "time": time.time()}) + "\n")
        out.flush()
        frames = split_frames(cap["timings"])
        try:
            a = analyse_frame(frames[0][0], frames[0][1], args.msb, args.invert)
            summary = f"{a['nbits']} bits: {hexs(a['bytes'])}"
        except ValueError:
            summary = "too short to decode (noise?)"
        print(f"  saved [{count}] {label!r}: {len(cap['timings'])} timings, {summary}")
        count += 1

    if args.stdin:
        parser = LogParser()
        for line in sys.stdin:
            cap = parser.feed(line)
            if cap:
                save_cap(cap, cap["label"])
        print(f"{count} capture(s) written to {args.out}")
        return

    try:
        import serial  # pyserial
    except ImportError:
        sys.exit("pyserial is needed for --port:  pip install pyserial\n"
                 "(or pipe the serial monitor in:  pio device monitor | python analyse_ir.py record --stdin)")
    ser = serial.Serial(args.port, args.baud, timeout=0.5)
    print(f"listening on {args.port} at {args.baud} baud; blank label to finish")
    parser = LogParser()
    try:
        while True:
            label = input("label for the next press (what did you change?): ").strip()
            if not label:
                break
            ser.reset_input_buffer()
            parser = LogParser()
            print("  press the button on the real remote now...")
            while True:
                cap = parser.feed(ser.readline().decode("utf-8", "replace"))
                if cap:
                    save_cap(cap, label)
                    break
    except (KeyboardInterrupt, EOFError):
        pass
    print(f"{count} capture(s) written to {args.out}")


# --------------------------------------------------------------------------
# self test
# --------------------------------------------------------------------------
def _synth(data, msb, invert, rng, jitter=0.08, frames=2):
    params = {"header": (3400, 1750), "bit_mark": 450, "short": 420, "long": 1300,
              "footer": 440, "gap": 15500}
    seq = build_timings(params, data, msb, invert, frames)
    out = []
    for t in seq:
        t = t * (1 + rng.uniform(-jitter, jitter))
        out.append(int(round(t / 2.0)) * 2)  # the receiver ticks at 2 us
    return out


def cmd_selftest(_args):
    rng = random.Random(1234)
    frame = [0x23, 0xCB, 0x26, 0x01, 0x00, 0x20, 0x18, 0x06, 0x36, 0xC0, 0x67,
             0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xB0]
    heavy_tail = [0x12, 0xED, 0x34, 0xCB]
    heavy = [0xAD, 0x51, 0x3C, 0xE5, 0x1A] + heavy_tail
    checks = 0
    for msb in (False, True):
        for invert in (False, True):
            for data in (frame, heavy):
                for trial in range(5):
                    t = _synth(data, msb, invert, rng, jitter=0.08 if trial else 0.0)
                    frames = split_frames(t)
                    assert len(frames) == 2, f"expected 2 frames, got {len(frames)}"
                    for fr, gap in frames:
                        a = analyse_frame(fr, gap, msb, invert)
                        assert a["bytes"] == data, (msb, invert, hexs(a["bytes"]), hexs(data))
                        assert a["nbits"] == len(data) * 8
                    checks += 1
    assert checksum_report(frame) == ["sum8 (last byte = sum of the others, mod 256)"], checksum_report(frame)
    assert any("inverted" in c for c in checksum_report(heavy)), checksum_report(heavy)
    assert fix_checksum(frame[:-1] + [0], "sum8") == frame
    # encode -> decode keeps the bytes and honours --fix-checksum
    p = {"header": (3400, 1750), "bit_mark": 450, "short": 420, "long": 1300, "footer": 440, "gap": 15500}
    forged = fix_checksum(frame[:-1] + [0], "sum8")
    t = build_timings(p, forged, False, False, 2)
    assert analyse_frame(split_frames(t)[1][0], None)["bytes"] == frame
    print(f"selftest OK ({checks} jittered round trips, both bit orders, both polarities)")


# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, frame=False):
        p.add_argument("--msb", action="store_true", help="pack bits MSB-first (default LSB-first)")
        p.add_argument("--invert", action="store_true",
                       help="treat a SHORT space as 1 (needed for Mitsubishi Heavy)")
        if frame:
            p.add_argument("--frame", type=int, default=0, help="which frame in the capture to use (default 0)")

    p = sub.add_parser("record", help="save labelled presses to a .jsonl file")
    p.add_argument("--port", help="serial port, e.g. /dev/ttyUSB0 or COM3")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--out", default="caps.jsonl")
    p.add_argument("--stdin", action="store_true", help="read the serial log from stdin instead of a port")
    common(p)
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("decode", help="decode every capture in a file (file or file:INDEX)")
    p.add_argument("file")
    common(p)
    p.set_defaults(fn=cmd_decode)

    p = sub.add_parser("table", help="byte columns side by side")
    p.add_argument("file")
    common(p, frame=True)
    p.set_defaults(fn=cmd_table)

    p = sub.add_parser("diff", help="bits that differ from a reference capture")
    p.add_argument("file")
    p.add_argument("--ref", type=int, default=0, help="index of the reference capture")
    common(p, frame=True)
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("encode", help="forge a frame from bytes, reusing a capture's timings")
    p.add_argument("--like", required=True, help="capture to copy timings from, FILE or FILE:INDEX")
    p.add_argument("--bytes", required=True, help='hex bytes, e.g. "23 CB 26 ..."')
    p.add_argument("--fix-checksum", choices=["sum8", "xor8", "none"], default="none")
    p.add_argument("--frames", type=int, help="how many times to send the frame (default: as captured)")
    p.add_argument("--gap", type=int, help="gap between frames in us (default: as captured)")
    common(p)
    p.set_defaults(fn=cmd_encode)

    p = sub.add_parser("emit", help="print a capture as a C array for sendRaw()")
    p.add_argument("file")
    p.add_argument("--index", type=int, default=0)
    p.set_defaults(fn=cmd_emit)

    p = sub.add_parser("selftest", help="synthetic round trip, no hardware needed")
    p.set_defaults(fn=cmd_selftest)

    args = ap.parse_args(argv)
    if args.cmd == "record" and not (args.port or args.stdin):
        ap.error("record needs --port PORT or --stdin")
    args.fn(args)


if __name__ == "__main__":
    main()
