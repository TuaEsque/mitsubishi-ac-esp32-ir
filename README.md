# Office AC automation: ESP32 + IR for a Mitsubishi MSZ-HR35VF

An ESP32 with an IR LED that replaces the remote, driven over Wi-Fi by anything
on your network (Home Assistant, cron, a script, curl). It can also listen to
your real remote and help you reverse engineer the signals.

```
aircon-ir/
  platformio.ini            two firmwares: `capture` and `controller`
  src/capture.cpp           prints what the real remote sends
  src/controller.cpp        HTTP API that sends IR
  include/ac_logic.h        request parsing + JSON (PC-testable, no Arduino code)
  include/config.h          pins and protocol defaults
  include/secrets.h.example Wi-Fi details (copy to secrets.h)
  tools/analyse_ir.py       record / decode / diff / forge raw captures (pure Python)
  tools/host_check.sh       PC-side tests and example generation
  tools/host/               test + example generator sources
  examples/                 sample captures from the library's encoders (not a real unit)
  homeassistant/office_ac.yaml   rest_command + scripts for the HTTP controller
  esphome/office-ac.yaml    alternative: ESPHome climate entity (not validated)
```

## 0. Before you build: check the shortcuts

1. **Which Mitsubishi is it?** The MSZ-HR35VF is a *Mitsubishi Electric* indoor
   unit. Mitsubishi Electric (MSZ-/MSY-/MFZ-) and *Mitsubishi Heavy Industries*
   (SRK/SRC) use different IR protocols. Start with `MITSUBISHI_AC`; the capture
   step tells you for sure (it may report `MITSUBISHI112` instead).
2. **IRremoteESP8266 already knows both families.** Capture one press; if the
   firmware prints `MITSUBISHI_AC`, `MITSUBISHI112`, `MITSUBISHI_HEAVY_88` or
   `MITSUBISHI_HEAVY_152`, skip step 3. The Python tool is for when the capture
   says `UNKNOWN`, or when you want to understand the frame.
3. **IR is not the only way in, and the wired one gives real feedback.** Many
   Mitsubishi Electric indoor units have a CN105 service port. The
   [MitsubishiCN105ESPHome](https://github.com/echavet/MitsubishiCN105ESPHome)
   project lists the MSZ-HR series among units contributors have tested (the
   HR35VF itself is not named, so check your unit has the port). The hardware
   is an ESP32, a 5 V/3.3 V level shifter and a JST PA-pin connector, and you
   get two-way control and real status in Home Assistant, which IR can never
   give. That project's README says ESPHome now also ships a native
   `mitsubishi_cn105` component. Mitsubishi's own Wi-Fi interface (MAC-587IF-E)
   is the paid, supported option; I did not verify it fits the HR35VF. Look at
   the unit's service manual before committing to IR.

## 1. Hardware

| Qty | Part | Notes |
|---|---|---|
| 1 | ESP32 dev board (e.g. ESP32-DevKitC) | An ESP8266 D1 mini also works (change `platform`/`board` in `platformio.ini`, and the pins). |
| 1 | 38 kHz IR receiver module (TSOP38238 or VS1838B) | Both Mitsubishi families use a 38 kHz carrier. **Check the datasheet pinout for your exact part.** Only needed for capture. |
| 1-2 | 940 nm IR LED (e.g. TSAL6200 or a 5 mm 940 nm) | Two LEDs aimed slightly apart give wider coverage. |
| 1 | NPN transistor (2N2222 / BC337) | An ESP32 pin alone cannot drive an IR LED at useful current. |
| 1 | ~1 kOhm resistor | Transistor base. |
| 1 | ~47 Ohm resistor | LED current limit from 5 V (about 70 mA pulsed). 100 Ohm is gentler. |
| 1 | Breadboard, jumper wires, USB cable and 5 V supply | A small perfboard and case for the final install. |
| opt | Phone camera | Most phone cameras show an IR LED flashing: a quick "is it transmitting?" test. |

All of it is commodity hobby electronics. I have not priced the parts.

### Wiring

```
Receiver (capture mode):          Transmitter (controller mode):

  OUT ---- GPIO14                   GPIO4 --[1k]-- base (2N2222)
  GND ---- GND                                       collector --- LED cathode (-)
  VCC ---- 3V3                                       emitter   --- GND
                                    5V --[47R]-- LED anode (+)
```

Both can be on the board at once (different pins). Keep the receiver away from
the LED while capturing, or it will see its own transmissions.

## 2. Capture your real remote

```bash
pip install platformio pyserial
pio run -e capture -t upload
pio device monitor        # 115200 baud; press a button on the original remote
```

Each press prints a block like this:

```
=== #1 t=4000ms
PROTO MITSUBISHI_AC bits=144 overflow=NO
STATE 23CB26010020180636C067000000000000B0
DESC Power: On, Mode: 3 (Cool), Temp: 22C, ...
RAW,583,3400,1750,450,1300,...
```

`PROTO` is the library's guess (`UNKNOWN` if it does not recognise the frame),
`STATE` the decoded bytes, `RAW` the mark/space timings in microseconds.

## 3. Reverse engineer (only if needed)

Record presses with a label saying what you did, **changing one thing at a
time** (start from a known state such as Cool / 22 / Fan auto, then change only
the temperature, then only the fan, and so on):

```bash
python tools/analyse_ir.py record --port /dev/ttyUSB0 --out caps.jsonl
#   or, without pyserial:  pio device monitor | python tools/analyse_ir.py record --stdin
python tools/analyse_ir.py decode caps.jsonl           # header, bit timings, length, checksum
python tools/analyse_ir.py table  caps.jsonl           # which byte columns vary
python tools/analyse_ir.py diff   caps.jsonl --ref 0   # exact bits that moved
```

What you will typically find with these remotes:

- Every press sends the **whole state** (power, mode, temperature, fan, vane),
  not a single "temp up" command. So you model the full state, which is why the
  library keeps one state struct and resends it each time.
- A frame is ~18 bytes, often sent twice, ending in a checksum (Mitsubishi
  Electric: the sum of the previous bytes, mod 256).
- Temperature is a small offset field (`degrees - 16`) plus a half-degree bit.

Try it without hardware using the examples (generated by the library's
encoders, **not** from a real unit):

```bash
python tools/analyse_ir.py decode examples/mitsubishi_electric_msz.log
python tools/analyse_ir.py decode examples/mitsubishi_heavy_152.log --invert
python tools/analyse_ir.py selftest
```

`decode` compares its bytes with the `STATE` line in the log and prints
MATCH/MISMATCH, so it is also a quick check that your bit order and polarity
settings are right.

Forge frames you never captured (recomputes the checksum, prints a C array for
`IRsend::sendRaw(rawData, n, 38)`):

```bash
python tools/analyse_ir.py encode --like caps.jsonl:1 \
    --bytes "23 CB 26 01 00 20 18 0A 36 C0 67 00 00 00 00 00 00 00" --fix-checksum sum8
```

Or replay a capture verbatim: `python tools/analyse_ir.py emit caps.jsonl --index 3`.
(A receiver module reads marks a little short and spaces a little long, so the
timings are good for analysis and usually fine for replay, but the library's
ideal timings in the controller are better for everyday use.)

## 4. Run the controller

```bash
cp include/secrets.h.example include/secrets.h     # add Wi-Fi details
# edit platformio.ini -> build_flags -> -DAC_PROTOCOL=... to match the capture
pio run -e controller -t upload
pio device monitor     # prints the IP and http://office-ac.local/
```

```bash
curl "http://<esp-ip>/ac?power=on&mode=cool&temp=22&fan=auto"
curl "http://<esp-ip>/ac?power=off"
curl "http://<esp-ip>/status"
```

Parameters (all optional; omitted ones keep their previous value):

| Parameter | Values |
|---|---|
| `power` | `on` `off` (also `1`/`0`/`true`/`false`) |
| `mode` | `auto` `cool` `heat` `dry` `fan` `off`. `off` switches the unit off; any other mode also switches it on unless `power=` is given |
| `temp` | 16 to 31, rounded to the nearest 0.5 |
| `fan` | `auto` `min` `low` `medium` `high` `max` |
| `swingv` | `off` `auto` `highest` `high` `middle` `low` `lowest`. On Mitsubishi Electric, `off` means "the unit chooses the vane position" and `auto` means "vane oscillates" |
| `key` | only if you set `API_KEY` in `secrets.h` |

A bad value or an unknown parameter returns HTTP 400 and **sends nothing**
(`mode=colo` is an error, not "auto"). A request with no parameters just
reports the state. Nothing is transmitted at boot.

## 5. Home Assistant

- **HTTP controller (this firmware):** `homeassistant/office_ac.yaml` is a
  package with a `rest_command`, "cool" and "off" scripts and an example
  evening switch-off. These are commands: IR cannot report state back.
- **ESPHome instead:** `esphome/office-ac.yaml` gives Home Assistant a real
  "Office AC" climate entity on the same hardware, using ESPHome's built-in
  `mitsubishi` IR platform. Flash it instead of the PlatformIO controller.
- **Wired CN105** (section 0) is the option that gives true two-way state.

## Things that will bite you

- **No feedback.** IR is one-way. If someone uses the real remote, your idea of
  the state is wrong. Treat `/status` as "what I last sent".
- **`overflow=YES`.** Increase `kCaptureBufferSize` in `src/capture.cpp`.
- **Nothing captured.** Check the receiver pinout, and that the remote is
  within about 30 cm, pointed at it.
- **Press split into two captures.** `kTimeout` in `capture.cpp` must exceed the
  gap between the repeated frames (15-17 ms).
- **Range.** If the unit only responds up close, use two LEDs or lower the 47 Ohm
  resistor (stay within the LED's pulsed-current rating).
- **Heavy Industries bit polarity.** Those frames use a short space for 1. Use
  `--invert` in the Python tool to line its bytes up with the library's `STATE`.
- **Plain HTTP.** Keep the device on your LAN. `API_KEY` only guards against accidents.

## Tests

```bash
git clone --depth 1 https://github.com/crankyoldgit/IRremoteESP8266.git
tools/host_check.sh ./IRremoteESP8266              # request parsing tests
tools/host_check.sh ./IRremoteESP8266 --examples   # also regenerate examples/
python tools/analyse_ir.py selftest
```

## Status of this code

Checked on a PC against IRremoteESP8266 v2.9.0 (master, Aug 2026):

- `tools/analyse_ir.py` decodes every example frame (8 Mitsubishi Electric,
  4 Heavy 152) to exactly the bytes the library's real encoder started from,
  and the `selftest`, `encode` round trip and `record --stdin` work.
- `include/ac_logic.h` passes its test suite (`tools/host/ac_logic_test.cpp`).
- `src/capture.cpp` and `src/controller.cpp` pass `g++ -fsyntax-only -Wall
  -Wextra` against the real library headers for all four `AC_PROTOCOL` values,
  with stand-ins for the Arduino, Wi-Fi and WebServer headers. That caught one
  typo, but it is not a real build.

**Not done:**

- The firmware has **not been built with PlatformIO or run on an ESP32**. The
  PlatformIO registry was unreachable where this was written. Expect to fix a
  small thing or two on the first build.
- Nothing has been tested against an actual MSZ-HR35VF. Which Mitsubishi frame
  its remote sends is unconfirmed until you capture it.
- `esphome/office-ac.yaml` has not been run through ESPHome, and the Home
  Assistant package has only had its URL template rendered with plain Jinja2.
