// ac_logic.h - request parsing and JSON for the aircon controller.
//
// Deliberately free of Arduino/ESP32 dependencies so it can be compiled and
// tested on a normal PC against the IRremoteESP8266 sources (see
// tools/host_check.sh). controller.cpp is a thin layer around this.
#pragma once

#include <math.h>
#include <cmath>
#include <cstdlib>
#include <stdio.h>

#include <string>
#include <utility>
#include <vector>

#include "IRsend.h"  // stdAc::state_t and the common enums

namespace aclogic {

using Params = std::vector<std::pair<std::string, std::string>>;

struct ParseResult {
  bool ok = true;
  bool changed = false;  // true if at least one control parameter was given
  std::string error;
};

constexpr float kMinTemp = 16.0f;
constexpr float kMaxTemp = 31.0f;

inline std::string lower(std::string s) {
  for (auto &c : s)
    if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
  return s;
}

inline bool parseBool(const std::string &v, bool &out) {
  const std::string s = lower(v);
  if (s == "on" || s == "true" || s == "1") {
    out = true;
    return true;
  }
  if (s == "off" || s == "false" || s == "0") {
    out = false;
    return true;
  }
  return false;
}

// "off" is accepted as a mode and means power off, as in Home Assistant.
inline bool parseMode(const std::string &v, stdAc::opmode_t &out) {
  const std::string s = lower(v);
  if (s == "auto") out = stdAc::opmode_t::kAuto;
  else if (s == "cool") out = stdAc::opmode_t::kCool;
  else if (s == "heat") out = stdAc::opmode_t::kHeat;
  else if (s == "dry") out = stdAc::opmode_t::kDry;
  else if (s == "fan" || s == "fan_only") out = stdAc::opmode_t::kFan;
  else if (s == "off") out = stdAc::opmode_t::kOff;
  else return false;
  return true;
}

inline bool parseFan(const std::string &v, stdAc::fanspeed_t &out) {
  const std::string s = lower(v);
  if (s == "auto") out = stdAc::fanspeed_t::kAuto;
  else if (s == "min" || s == "quiet") out = stdAc::fanspeed_t::kMin;
  else if (s == "low") out = stdAc::fanspeed_t::kLow;
  else if (s == "medium" || s == "med") out = stdAc::fanspeed_t::kMedium;
  else if (s == "high") out = stdAc::fanspeed_t::kHigh;
  else if (s == "max") out = stdAc::fanspeed_t::kMax;
  else return false;
  return true;
}

inline bool parseSwingV(const std::string &v, stdAc::swingv_t &out) {
  const std::string s = lower(v);
  if (s == "off") out = stdAc::swingv_t::kOff;
  else if (s == "auto") out = stdAc::swingv_t::kAuto;
  else if (s == "highest") out = stdAc::swingv_t::kHighest;
  else if (s == "high") out = stdAc::swingv_t::kHigh;
  else if (s == "middle") out = stdAc::swingv_t::kMiddle;
  else if (s == "low") out = stdAc::swingv_t::kLow;
  else if (s == "lowest") out = stdAc::swingv_t::kLowest;
  else return false;
  return true;
}

inline const char *modeName(stdAc::opmode_t m) {
  switch (m) {
    case stdAc::opmode_t::kAuto: return "auto";
    case stdAc::opmode_t::kCool: return "cool";
    case stdAc::opmode_t::kHeat: return "heat";
    case stdAc::opmode_t::kDry: return "dry";
    case stdAc::opmode_t::kFan: return "fan";
    default: return "off";
  }
}

inline const char *fanName(stdAc::fanspeed_t f) {
  switch (f) {
    case stdAc::fanspeed_t::kMin: return "min";
    case stdAc::fanspeed_t::kLow: return "low";
    case stdAc::fanspeed_t::kMedium: return "medium";
    case stdAc::fanspeed_t::kHigh: return "high";
    case stdAc::fanspeed_t::kMax: return "max";
    default: return "auto";
  }
}

inline const char *swingVName(stdAc::swingv_t s) {
  switch (s) {
    case stdAc::swingv_t::kAuto: return "auto";
    case stdAc::swingv_t::kHighest: return "highest";
    case stdAc::swingv_t::kHigh: return "high";
    case stdAc::swingv_t::kMiddle: return "middle";
    case stdAc::swingv_t::kLow: return "low";
    case stdAc::swingv_t::kLowest: return "lowest";
    default: return "off";
  }
}

// Strict decimal parse of a float: no trailing junk, no empty string.
inline bool parseFloat(const std::string &v, float &out) {
  if (v.empty()) return false;
  char *end = nullptr;
  const double d = strtod(v.c_str(), &end);
  if (end == v.c_str() || *end != '\0' || !std::isfinite(d)) return false;
  out = static_cast<float>(d);
  return true;
}

// Applies query parameters to `state`. Nothing is modified unless every
// parameter is valid. Unknown parameters are an error so typos don't silently
// do nothing. "key" is ignored here (the web layer checks it).
inline ParseResult applyParams(stdAc::state_t &state, const Params &params) {
  ParseResult r;
  stdAc::state_t next = state;
  bool powerGiven = false;

  for (const auto &kv : params) {
    const std::string name = lower(kv.first);
    const std::string &val = kv.second;
    if (name == "key" || name == "plain") continue;

    if (name == "power") {
      bool on;
      if (!parseBool(val, on)) {
        r.ok = false;
        r.error = "power must be on or off";
        return r;
      }
      next.power = on;
      powerGiven = true;
    } else if (name == "mode") {
      stdAc::opmode_t m;
      if (!parseMode(val, m)) {
        r.ok = false;
        r.error = "mode must be auto, cool, heat, dry, fan or off";
        return r;
      }
      if (m == stdAc::opmode_t::kOff) {
        next.power = false;
      } else {
        next.mode = m;
        // Setting a mode implies turning on unless power= is given too.
        if (!powerGiven) next.power = true;
      }
    } else if (name == "temp") {
      float t;
      if (!parseFloat(val, t) || t < kMinTemp || t > kMaxTemp) {
        r.ok = false;
        r.error = "temp must be a number from 16 to 31";
        return r;
      }
      next.degrees = roundf(t * 2.0f) / 2.0f;  // nearest half degree
      next.celsius = true;
    } else if (name == "fan") {
      stdAc::fanspeed_t f;
      if (!parseFan(val, f)) {
        r.ok = false;
        r.error = "fan must be auto, min, low, medium, high or max";
        return r;
      }
      next.fanspeed = f;
    } else if (name == "swingv") {
      stdAc::swingv_t s;
      if (!parseSwingV(val, s)) {
        r.ok = false;
        r.error = "swingv must be off, auto, highest, high, middle, low or lowest";
        return r;
      }
      next.swingv = s;
    } else {
      r.ok = false;
      r.error = "unknown parameter: " + kv.first;
      return r;
    }
    r.changed = true;
  }

  // An explicit power=off wins over an implied power-on from mode=.
  for (const auto &kv : params) {
    if (lower(kv.first) == "power") {
      bool on;
      if (parseBool(kv.second, on)) next.power = on;
    }
  }

  state = next;
  return r;
}

// secondsSinceSend < 0 means "nothing sent since boot".
inline std::string toJson(const stdAc::state_t &s, const char *protocol,
                          long secondsSinceSend) {
  char buf[320];
  char since[24];
  if (secondsSinceSend < 0) snprintf(since, sizeof since, "null");
  else snprintf(since, sizeof since, "%ld", secondsSinceSend);
  snprintf(buf, sizeof buf,
           "{\"power\":%s,\"mode\":\"%s\",\"temp\":%.1f,\"fan\":\"%s\","
           "\"swingv\":\"%s\",\"protocol\":\"%s\",\"last_sent_s_ago\":%s,"
           "\"note\":\"last command sent; IR is one-way, real state may differ\"}",
           s.power ? "true" : "false", modeName(s.mode),
           static_cast<double>(s.degrees), fanName(s.fanspeed),
           swingVName(s.swingv), protocol, since);
  return std::string(buf);
}

inline std::string errorJson(const std::string &msg) {
  std::string out = "{\"error\":\"";
  for (char c : msg) {
    if (c == '"' || c == '\\') out += '\\';
    if (static_cast<unsigned char>(c) >= 0x20) out += c;
  }
  out += "\"}";
  return out;
}

}  // namespace aclogic
