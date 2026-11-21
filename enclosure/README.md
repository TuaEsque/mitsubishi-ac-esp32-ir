# Enclosure

A 3D-printable box for the perfboard (5 × 7 cm, uncut), modelled in [build123d](https://github.com/gumyr/build123d) in `perfboard_box.py`. The board screws onto four standoffs under its corner mounting holes, and the lid screws onto four corner bosses.

Outside it measures 74.5 × 80.5 × 30.6 mm (inside 70.5 × 76.5 × 26.6 mm). There is 20 mm from the board's top surface to the lid, over the 16.5 mm ESP32 module.

| Feature | Where | Notes |
| --- | --- | --- |
| Board standoffs | Under the corner mounting holes | 5 mm tall (room for the solder joints), Ø2.2 mm pilots (widened from 1.7 mm after the first fit test) for **M2 × 6 self-tapping** screws, each tied to the end wall with a rib |
| Lid bosses | Inside corners | Ø2.5 mm pilots for **M3 × 8 self-tapping** screws; Ø3.4 mm holes in the lid |
| USB slot | Row-1 wall, centred on the ESP32 | 15 × 8 mm, big enough for a micro-USB or USB-C plug's overmould. The ESP32 module sticks out 5 mm past the board's row-1 edge, so that end has a 5.5 mm gap: the module stops 0.5 mm short of the wall |
| IR LED window | Column-R wall (faces the AC) | 21 × 11 mm, spans both LEDs with room for their ~10° splay. The wall is 12.5 mm from the board edge for the 12 mm LEDs |
| Receiver hole | Antenna-end wall, opposite the USB slot | Ø7.0 mm for the 5 mm receiver head (prints at about 6.8 mm), 6 mm above the board, over the empty strip columns (column O) so the lead stays clear of the ESP32. Push the TSOP38238's dome into it from inside and fix it with a dab of hot glue |

## Build it

```bash
pip install build123d ocp_vscode      # ocp_vscode only for the VS Code preview
python enclosure/perfboard_box.py     # writes enclosure/out/, previews in OCP CAD Viewer
python enclosure/perfboard_box.py --no-show
```

Outputs in `out/`: `base.stl`, `lid.stl` (already flat for printing), `fit_test.stl` and `enclosure.step`.

The script works out every position as numbers first, then `check_layout()` checks for clashes (standoffs against lid bosses, bosses against the board edge, wall above the USB slot, and so on). It stops without exporting if anything is closer than 1 mm.

## Measure before the full print

The board grid (columns, rows, LED holes, ESP32 sockets) comes from `tools/perfboard.py`. The LED protrusion (12 mm), the ESP32 module height (16.5 mm) and its overhang past the row-1 edge (5 mm) are measured. The values still marked `MEASURE` in the script are estimates:

1. **Mounting holes**: `MOUNT_PITCH_W` × `MOUNT_PITCH_L` = 46.4 × 66.0 mm centre to centre, Ø2.0 mm. This is Adafruit's spec for this board style. With calipers, measure edge to edge across two holes and subtract one hole diameter.
2. **`USB_Z_ABOVE_BOARD`** (14 mm): from the board's top surface to the middle of the USB socket.

Then print `fit_test.stl` (the floor, the standoffs and the bottom 1.5 mm of the walls) and screw the board down. If the holes line up and the board drops in, print the base and lid.

## Printing

- PLA, 0.2 mm layers, 3 walls, 15-20 % infill, no supports. The window and slot tops are short bridges.
- Base: open side up. Lid: as exported, flat.
- Plain PLA blocks IR, so the LEDs need the open window. Don't cover it with tape or a coloured film.
