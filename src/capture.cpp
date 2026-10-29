// Capture firmware: prints what your real remote sends.
//
// Wire the receiver's OUT pin to IR_RECV_PIN, point the remote at it from
// ~30 cm, press a button, read the serial monitor (115200 baud).
//
// Each press prints a block like this (tools/analyse_ir.py reads it):
//
//   === #3 t=48210ms
//   PROTO MITSUBISHI_AC bits=144 overflow=NO
//   STATE 23CB260100201806 ...        (only for protocols the library decodes)
//   DESC Power: On, Mode: 3 (Cool), Temp: 22C, ...
//   RAW,583,3400,1750,450,1300,...    (mark, space, mark, ... in microseconds)
//
// PROTO says UNKNOWN when the library does not recognise the frame; that is
// when tools/analyse_ir.py earns its keep.

#include <Arduino.h>
#include <IRac.h>
#include <IRrecv.h>
#include <IRremoteESP8266.h>
#include <IRutils.h>

#include "config.h"

// Air-con frames are long (Mitsubishi Electric: 291 timings per frame, two
// frames per press). 1024 fits that with room to spare. If PROTO shows
// overflow=YES, raise this.
const uint16_t kCaptureBufferSize = 1024;

// Milliseconds of silence that end a capture. It must be longer than the gap
// between the repeated frames of one press (~15-17 ms for Mitsubishi), or each
// press is split into two captures. 50 ms is the library's own choice for A/Cs.
const uint8_t kTimeout = 50;

IRrecv irrecv(IR_RECV_PIN, kCaptureBufferSize, kTimeout, true);
decode_results results;
static uint32_t pressCount = 0;

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("\nIR capture ready on GPIO%d (IRremoteESP8266 v%s)\n", IR_RECV_PIN,
                _IRREMOTEESP8266_VERSION_STR);
#if DECODE_HASH
  irrecv.setUnknownThreshold(12);  // ignore tiny bursts of noise
#endif
  irrecv.setTolerance(kTolerance);
  irrecv.enableIRIn();
}

void loop() {
  if (!irrecv.decode(&results)) {
    delay(5);
    return;
  }
  pressCount++;
  Serial.printf("=== #%lu t=%lums\n", (unsigned long)pressCount, (unsigned long)millis());
  Serial.printf("PROTO %s bits=%u overflow=%s\n",
                typeToString(results.decode_type, results.repeat).c_str(), results.bits,
                results.overflow ? "YES" : "NO");

  if (hasACState(results.decode_type) && results.bits >= 8) {
    Serial.print("STATE ");
    for (uint16_t i = 0; i < results.bits / 8; i++) Serial.printf("%02X", results.state[i]);
    Serial.println();
  }
  String description = IRAcUtils::resultAcToString(&results);
  if (description.length()) Serial.printf("DESC %s\n", description.c_str());

  // The raw timings in microseconds, header mark first.
  uint16_t *raw = resultToRawArray(&results);
  uint16_t len = getCorrectedRawLength(&results);
  if (raw != nullptr) {
    Serial.printf("RAW,%u", len);
    for (uint16_t i = 0; i < len; i++) Serial.printf(",%u", raw[i]);
    Serial.println();
    delete[] raw;
  }
  Serial.println();
  Serial.flush();
}
