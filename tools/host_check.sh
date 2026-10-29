#!/bin/sh
# PC-side checks, no ESP32 needed. Compiles the IRremoteESP8266 sources in
# their unit-test mode, then:
#   1. runs tools/host/ac_logic_test.cpp (request parsing + JSON of the controller)
#   2. with --examples, regenerates examples/*.log with the library's REAL
#      Mitsubishi encoders (tools/host/gen_examples.cpp)
#
#   git clone --depth 1 https://github.com/crankyoldgit/IRremoteESP8266.git
#   tools/host_check.sh ./IRremoteESP8266 [--examples]
#
# Build products go to $TMPDIR (default /tmp/aircon-host-build).
set -eu
LIB=${1:?usage: tools/host_check.sh /path/to/IRremoteESP8266 [--examples]}
MODE=${2:-}
HERE=$(cd "$(dirname "$0")/.." && pwd)
BUILD=${TMPDIR:-/tmp}/aircon-host-build
mkdir -p "$BUILD"
DEFS="-std=gnu++11 -O0 -DUNIT_TEST -D_IR_LOCALE_=en-AU"
LIBFLAGS="$DEFS -w -I$LIB/src -I$LIB/test"
# -isystem keeps warnings from the library headers out of our own diagnostics.
MYFLAGS="$DEFS -Wall -Wextra -isystem $LIB/src -isystem $LIB/test -I$HERE/include"

# Library objects (only rebuilt when missing; delete $BUILD to force).
for f in "$LIB"/src/*.cpp; do
  o="$BUILD/$(basename "$f" .cpp).o"
  [ -f "$o" ] || echo "g++ $LIBFLAGS -c $f -o $o"
done | xargs -P "$(nproc 2>/dev/null || echo 2)" -I{} sh -c '{}'

g++ $MYFLAGS "$HERE/tools/host/ac_logic_test.cpp" "$BUILD"/*.o -o "$BUILD/ac_logic_test"
"$BUILD/ac_logic_test"

if [ "$MODE" = "--examples" ]; then
  g++ $MYFLAGS "$HERE/tools/host/gen_examples.cpp" "$BUILD"/*.o -o "$BUILD/gen_examples"
  "$BUILD/gen_examples" electric > "$HERE/examples/mitsubishi_electric_msz.log"
  "$BUILD/gen_examples" heavy    > "$HERE/examples/mitsubishi_heavy_152.log"
  echo "examples/ regenerated"
fi
