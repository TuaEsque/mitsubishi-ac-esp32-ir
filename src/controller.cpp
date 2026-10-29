// Controller firmware: a tiny HTTP API that replaces the IR remote.
//
//   GET /ac?power=on&mode=cool&temp=22&fan=auto[&swingv=off][&key=SECRET]
//   GET /status
//   GET /            (usage)
//
// Only the parameters you pass are changed; everything else keeps its previous
// value. Every request that changes something transmits the WHOLE state, which
// is what the real remote does. Parsing and validation live in
// include/ac_logic.h (unit tested on a PC, see tools/host_check.sh).
//
// IR is one-way: /status reports what this device LAST SENT, not what the unit
// is actually doing (someone may have used the real remote since).

#include <Arduino.h>
#include <IRac.h>
#include <IRremoteESP8266.h>
#include <IRsend.h>
#include <IRutils.h>

#ifdef ESP8266
#include <ESP8266WebServer.h>
#include <ESP8266WiFi.h>
#include <ESP8266mDNS.h>
using HttpServer = ESP8266WebServer;
#else
#include <ESPmDNS.h>
#include <WebServer.h>
#include <WiFi.h>
using HttpServer = WebServer;
#endif

#include "ac_logic.h"
#include "config.h"
#include "secrets.h"

static const decode_type_t kProtocol = decode_type_t::AC_PROTOCOL;

IRac ac(IR_LED_PIN);
HttpServer server(80);

static stdAc::state_t g_state;  // what we believe the unit is set to
static stdAc::state_t g_prev;   // what we last put on the wire
static bool g_everSent = false;
static uint32_t g_lastSentMs = 0;
static uint32_t g_lastWifiCheck = 0;

// ---------------------------------------------------------------- sending
static void initState() {
  g_state.protocol = kProtocol;
  g_state.model = -1;
  g_state.power = false;  // nothing is transmitted until the first request
  g_state.mode = stdAc::opmode_t::kCool;
  g_state.degrees = 24;
  g_state.celsius = true;
  g_state.fanspeed = stdAc::fanspeed_t::kAuto;
  // For Mitsubishi Electric "off" = the unit chooses the vane position and
  // "auto" = the vane oscillates continuously.
  g_state.swingv = stdAc::swingv_t::kOff;
}

// Transmit `s`. On success it becomes the current state.
static bool sendState(const stdAc::state_t &s) {
  bool ok = ac.sendAc(s, g_everSent ? &g_prev : nullptr);
  if (ok) {
    g_state = s;
    g_prev = s;
    g_everSent = true;
    g_lastSentMs = millis();
  }
  return ok;
}

// ---------------------------------------------------------------- replies
static void replyJson(int code, const std::string &body) {
  server.sendHeader("Cache-Control", "no-store");
  server.send(code, "application/json", body.c_str());
}

static void replyStatus() {
  long age = g_everSent ? (long)((millis() - g_lastSentMs) / 1000) : -1;
  replyJson(200, aclogic::toJson(g_state, typeToString(kProtocol).c_str(), age));
}

static bool authorised() {
  if (strlen(API_KEY) == 0) return true;
  return server.arg("key") == API_KEY;
}

// ---------------------------------------------------------------- handlers
static void handleAc() {
  if (!authorised()) return replyJson(401, aclogic::errorJson("bad or missing key"));

  aclogic::Params params;
  for (int i = 0; i < server.args(); i++)
    params.emplace_back(server.argName(i).c_str(), server.arg(i).c_str());

  stdAc::state_t next = g_state;
  aclogic::ParseResult r = aclogic::applyParams(next, params);
  if (!r.ok) return replyJson(400, aclogic::errorJson(r.error));

  if (r.changed && !sendState(next))
    return replyJson(500, aclogic::errorJson("protocol not supported by this library build"));
  replyStatus();  // no parameters = just report, nothing is transmitted
}

static void handleStatus() {
  if (!authorised()) return replyJson(401, aclogic::errorJson("bad or missing key"));
  replyStatus();
}

static void handleRoot() {
  server.send(200, "text/plain",
              "Office AC IR controller\n"
              "  /ac?power=on|off  mode=auto|cool|heat|dry|fan|off  temp=16..31  "
              "fan=auto|min|low|medium|high|max\n"
              "      swingv=off|auto|highest|high|middle|low|lowest  [key=...]\n"
              "  /status\n");
}

// ---------------------------------------------------------------- wifi
static void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(HOSTNAME);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("Connecting to %s", WIFI_SSID);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(300);
    Serial.print('.');
  }
  if (WiFi.status() == WL_CONNECTED)
    Serial.printf("\nConnected, IP %s\n", WiFi.localIP().toString().c_str());
  else
    Serial.println("\nNot connected yet, will keep retrying");
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.printf("\nOffice AC controller, protocol %s on GPIO%d\n", typeToString(kProtocol).c_str(),
                IR_LED_PIN);
  if (!IRac::isProtocolSupported(kProtocol))
    Serial.println("WARNING: this protocol is not supported by IRac, sends will fail");

  initState();
  connectWifi();
  if (MDNS.begin(HOSTNAME)) {
    MDNS.addService("http", "tcp", 80);
    Serial.printf("mDNS: http://%s.local/\n", HOSTNAME);
  }

  server.on("/", handleRoot);
  server.on("/ac", handleAc);
  server.on("/status", handleStatus);
  server.onNotFound([]() { replyJson(404, aclogic::errorJson("not found")); });
  server.begin();
  Serial.println("HTTP server started. Example: /ac?power=on&mode=cool&temp=22&fan=auto");
}

void loop() {
  server.handleClient();
#ifdef ESP8266
  MDNS.update();
#endif
  if (millis() - g_lastWifiCheck > 10000) {
    g_lastWifiCheck = millis();
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("Wi-Fi lost, reconnecting");
      WiFi.reconnect();
    }
  }
}
