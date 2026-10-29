#pragma once
// Shared settings for both firmwares. Every value can be overridden from
// platformio.ini with -D flags.

// GPIO that drives the IR LED (through the transistor). ESP32: GPIO4.
#ifndef IR_LED_PIN
#define IR_LED_PIN 4
#endif

// GPIO connected to the OUT pin of the 38 kHz IR receiver (capture firmware).
#ifndef IR_RECV_PIN
#define IR_RECV_PIN 14
#endif

// Protocol the controller sends. Set in platformio.ini (-DAC_PROTOCOL=...).
// Mitsubishi Electric MSZ units normally use MITSUBISHI_AC; confirm with the
// capture firmware before relying on it.
#ifndef AC_PROTOCOL
#define AC_PROTOCOL MITSUBISHI_AC
#endif
