# Office AC automation: final build guide (29 Oct 2026, ESPHome)

This is the current reference for parts, wiring and the build. Superseded files (hardware.md, build-and-enclosure.md and the pre-ESPHome versions of this guide, README.md and the YAML files) are in the archive folder. The firmware is now ESPHome (esphome/office-ac.yaml), which makes "Office AC" a device in Home Assistant. README.md covers the software side; where it differs from this guide on parts or wiring, this guide wins.

## Status

| Item | Status |
| :---- | :---- |
| ESP32 boards (2 x DOIT 30-pin) | in hand |
| Other parts (see *Parts* below) | in hand |
| Transistor | **still to buy** (needed before the AC can be controlled; the receiver test works without it) |
| Solder | own reel: Sn-0.7Cu, 2% flux, 1 mm |
| Tools | own: soldering iron, multimeter, drill, side cutters |

## Parts

Typical UK prices (late 2026, inc VAT, before postage). They are ranges to budget with, not quotes; check current prices before buying.

| Qty | Item | Typical price |
| :---- | :---- | :---- |
| 1-2 | ESP32 WROOM-32 dev board, DOIT DevKit V1 style, 30-pin (a spare is handy) | £4-£10 each |
| 1 | TSOP38238 38 kHz IR receiver | £1-£2 |
| 2+ | 5 mm 940 nm IR LED (packs of 10-25 are the best value) | £2-£8 per pack |
| 1 | NPN transistor, 2N2222A / PN2222A, TO-92 (see options below) | £1-£3 for 5-10 |
| 3 | 100 ohm resistor, 1/4 W | £1-£2 per pack |
| 1 | 470 ohm resistor, 1/4 W | £1-£2 per pack |
| 1 set | Female 2.54 mm header strips: 15 holes per side (10-pin + 5-pin end to end works) | £1-£3 |
| 1 | Proto PCB 5 x 7 cm (2.54 mm pitch, 1.6 mm, 18 x 24 pads, pads not connected) | £3-£6 for a pack |
| 2 | Mini breadboard (170 points), for testing before soldering | £1-£2 each |
| 1 set | Jumper wires: male-male, female-male, female-female | £2-£6 |
| 1 | USB-A to micro-USB data cable (check your board's connector) | £2-£4 |
| 1 | Enclosure (project box, or 3D-printed) | £3-£8 |

Expect roughly **£25-£50** in total, depending on pack sizes and postage. A mixed resistor kit (£5-£10) is better value if you have none.

Suggested stores:

- **The Pi Hut, Pimoroni**: hobby parts, small packs, reliable stock information.
- **CPC (Farnell), RS, Rapid Electronics**: distributors; cheapest for transistors and resistors, but check minimum order and delivery charges.
- **Amazon, eBay**: multipacks and ESP32 boards from UK sellers; check the listing names the exact part.
- **AliExpress**: cheapest for ESP32 boards and LEDs, but delivery takes weeks.

## Transistor options (NPN, \~65 mA switching, TO-92)

- PN2222A / 2N2222A (plastic, usually emitter-base-collector). Available from the distributors above in packs of 5-10.
- Any 2N2222 / 2N2222A you already own. Metal can (TO-18) and plastic types have different pin orders, and "P2N2222A" has emitter and collector swapped. Check the datasheet.
- 2N3904 or S8050 (same emitter-base-collector order as PN2222), or BC337 (usually collector-base-emitter, the mirror of PN2222's emitter-base-collector). Mixed transistor multipacks often include PNP parts (2N2907, 2N3906, BC327), which will not work here.

Always confirm the pinout with the multimeter diode test before wiring: the base conducts to both other legs at about 0.6-0.7 V and reads open the other way; the emitter is usually the leg that reads slightly higher.

## Wiring (DOIT 30-pin board; matches esphome/office-ac.yaml: LED on GPIO4, receiver on GPIO14)

Receiver (permanent: it lets Home Assistant follow presses on the real remote):

- TSOP38238 pin 1 (OUT) to GPIO14, pin 2 to GND, pin 3 to **3V3** (not 5 V: ESP32 pins are not 5 V tolerant). Check the pin order on your part's datasheet before powering.

IR LED stage:

- **VIN** (about 5 V when USB powered) \-\> two 100 ohm resistors in parallel (about 50 ohm) \-\> LED anode  
- LED cathode \-\> transistor collector  
- transistor emitter \-\> GND  
- GPIO4 \-\> 470 ohm \-\> transistor base

Expected currents: LED about 62 mA (inside its 100 mA continuous / 1 A pulsed rating), base about 5.5 mA.

## Build order

1. Install ESPHome: the *ESPHome Device Builder* add-on in Home Assistant, or `pip install esphome` on your PC (README section 2). Use 2.4 GHz Wi-Fi.
2. Fill in secrets.yaml from esphome/secrets.yaml.example (Wi-Fi, fallback hotspot password, API key).
3. **Receiver test** (needs only the ESP32 and receiver, no transistor yet): plug female jumper ends onto the ESP32's header pins and the male ends into a mini breadboard holding the receiver. Uncomment `dump: all` in office-ac.yaml and flash over USB (README section 3). Open the logs and press buttons on the real remote from about 30 cm. A decoded Mitsubishi frame in the log confirms the receiver and the protocol.
4. Add the device in Home Assistant: Settings -> Devices & services -> *Discovered* ESPHome -> *Configure*, with the same API key. Press a button on the real remote: the Office AC thermostat card should follow it.
5. **LED stage** (once the transistor arrives): build it on the second mini breadboard, check the LED flashes on a phone camera when you change the mode in Home Assistant, then test Cool / 22 C on the unit from about 2 m.
6. Set `set_fan_mode` to match the number of fan speeds on the remote, comment `dump: all` out again, and install wirelessly.
7. Solder to the proto PCB: female headers (10-pin + 5-pin end to end, two rows) so the ESP32 plugs in. Plug the sockets onto the ESP32's pins first to hold the spacing while soldering.
8. Enclosure: drill about 5 mm holes in the wall facing the AC unit for two LEDs angled slightly apart, and one about 5 mm hole facing into the room for the receiver. Cut a slot for the USB cable and mount the board in the lid's 1.6 mm PCB guides (or stick-on pads).
9. Give the board a DHCP reservation. Home Assistant finds it by name, but a fixed address makes troubleshooting easier.

## First-build things to watch

- The ESPHome config passes validation on ESPHome 2026.10.1 but has not been compiled yet. The first compile downloads the ESP-IDF toolchain and takes several minutes; later ones are quick.
- Flashing from the add-on with *Plug into this computer* needs Chrome or Edge and the dashboard opened over HTTPS.
- Some DOIT-style boards need the BOOT button held while "Connecting..." shows during upload.
- A CP2102 or CH340 USB chip may need a driver on Windows. Board listings do not always say which.
- Confirm the board's USB connector is micro-USB and matches your cable.
- Before first power-up, use continuity mode: no beep between 3V3 and GND, or VIN and GND, and none between neighbouring socket pins (solder bridges).
- Solder: Sn-0.7Cu melts at 227 C, so run the tip hot (typically 330-370 C) and feed sparingly with 1 mm wire.

## Not used / alternatives considered

- Arduino Nano ESP32: needs pins A3/A7 instead of 4/14, LED supply from VBUS (not VIN), and carries extra library risk on the ESP32-S3. Not chosen.  
- Wired CN105 route (README section 0): would give two-way state; not part of this build.  
- PlatformIO HTTP controller (src/controller.cpp): an alternative, but Home Assistant only sees commands, not a device. Kept as a fallback with the capture firmware.
