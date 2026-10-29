// Host-side tests for include/ac_logic.h (no gtest needed).
#include <stdio.h>
#include <string.h>

#include "ac_logic.h"

static int g_fail = 0;
#define CHECK(cond)                                                    \
  do {                                                                 \
    if (!(cond)) {                                                     \
      printf("FAIL line %d: %s\n", __LINE__, #cond);                   \
      g_fail++;                                                        \
    }                                                                  \
  } while (0)

using namespace aclogic;

static stdAc::state_t fresh() {
  stdAc::state_t s;
  s.protocol = decode_type_t::MITSUBISHI_AC;
  s.power = false;
  s.mode = stdAc::opmode_t::kCool;
  s.degrees = 22;
  s.fanspeed = stdAc::fanspeed_t::kAuto;
  s.swingv = stdAc::swingv_t::kAuto;
  return s;
}

int main() {
  {  // typical request
    auto s = fresh();
    auto r = applyParams(s, {{"power", "on"}, {"mode", "cool"}, {"temp", "21"},
                             {"fan", "high"}});
    CHECK(r.ok && r.changed);
    CHECK(s.power && s.mode == stdAc::opmode_t::kCool && s.degrees == 21.0f);
    CHECK(s.fanspeed == stdAc::fanspeed_t::kHigh);
  }
  {  // mode alone implies power on
    auto s = fresh();
    auto r = applyParams(s, {{"mode", "heat"}});
    CHECK(r.ok && s.power && s.mode == stdAc::opmode_t::kHeat);
  }
  {  // explicit power=off wins whatever the parameter order
    auto s = fresh();
    auto r = applyParams(s, {{"power", "off"}, {"mode", "cool"}});
    CHECK(r.ok && !s.power);
    s = fresh();
    r = applyParams(s, {{"mode", "cool"}, {"power", "off"}});
    CHECK(r.ok && !s.power);
  }
  {  // mode=off means power off and keeps the previous mode
    auto s = fresh();
    s.power = true;
    auto r = applyParams(s, {{"mode", "off"}});
    CHECK(r.ok && !s.power && s.mode == stdAc::opmode_t::kCool);
  }
  {  // temperature rounding and limits
    auto s = fresh();
    CHECK(applyParams(s, {{"temp", "22.3"}}).ok && s.degrees == 22.5f);
    CHECK(applyParams(s, {{"temp", "22.2"}}).ok && s.degrees == 22.0f);
    CHECK(applyParams(s, {{"temp", "16"}}).ok && s.degrees == 16.0f);
    CHECK(applyParams(s, {{"temp", "31"}}).ok && s.degrees == 31.0f);
    CHECK(!applyParams(s, {{"temp", "15.5"}}).ok);
    CHECK(!applyParams(s, {{"temp", "31.5"}}).ok);
    CHECK(!applyParams(s, {{"temp", "abc"}}).ok);
    CHECK(!applyParams(s, {{"temp", ""}}).ok);
    CHECK(!applyParams(s, {{"temp", "22abc"}}).ok);
    CHECK(!applyParams(s, {{"temp", "nan"}}).ok);
    CHECK(s.degrees == 31.0f);  // unchanged by the failures
  }
  {  // all-or-nothing: a bad parameter leaves the state untouched
    auto s = fresh();
    auto r = applyParams(s, {{"temp", "20"}, {"fan", "turbo"}});
    CHECK(!r.ok && s.degrees == 22.0f && !s.power);
    CHECK(r.error.find("fan") != std::string::npos);
  }
  {  // unknown parameters are errors, key is ignored
    auto s = fresh();
    CHECK(!applyParams(s, {{"tmp", "22"}}).ok);
    auto r = applyParams(s, {{"key", "secret"}});
    CHECK(r.ok && !r.changed);
  }
  {  // swing and case-insensitivity
    auto s = fresh();
    CHECK(applyParams(s, {{"SWINGV", "Lowest"}, {"Fan", "MAX"}}).ok);
    CHECK(s.swingv == stdAc::swingv_t::kLowest);
    CHECK(s.fanspeed == stdAc::fanspeed_t::kMax);
    CHECK(!applyParams(s, {{"swingv", "sideways"}}).ok);
  }
  {  // JSON output
    auto s = fresh();
    s.power = true;
    s.degrees = 22.5f;
    std::string j = toJson(s, "MITSUBISHI_AC", 12);
    CHECK(j.find("\"power\":true") != std::string::npos);
    CHECK(j.find("\"temp\":22.5") != std::string::npos);
    CHECK(j.find("\"mode\":\"cool\"") != std::string::npos);
    CHECK(j.find("\"last_sent_s_ago\":12") != std::string::npos);
    CHECK(toJson(s, "X", -1).find("\"last_sent_s_ago\":null") != std::string::npos);
    CHECK(errorJson("bad \"x\"\n") == "{\"error\":\"bad \\\"x\\\"\"}");
  }
  if (g_fail) {
    printf("%d check(s) failed\n", g_fail);
    return 1;
  }
  printf("ac_logic: all checks passed\n");
  return 0;
}
