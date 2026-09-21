#!/usr/bin/env bash
# Copyright (C) 2026 James Lander, The Thinking Home
# Licensed under GPL-3.0-or-later. See the LICENSE file in this repository.
# Device Sentinel - a Home Assistant custom integration from The Thinking Home (xeazy.com)
#   Article: https://xeazy.com/reliable-home-assistant-dead-sensor-detection/
#   Repository: https://github.com/TheThinkingHome/device_sentinel
# File: tools/setup_container.sh, Version: 0.22.12 (2026-09-21)
#
# Rebuild the whole test environment in a fresh build container.
#
# Every chat starts with an empty container, and rebuilding the two
# harnesses by hand cost most of an hour and got a detail wrong more
# than once. This script is the record of what the environment is, so
# the next session reads one file instead of a transcript.
#
# Run it from the repository root. It reads the two pin files that live
# beside it, so the environment always matches the tree it was cloned
# from rather than a version written down somewhere else.
#
#   git clone https://github.com/TheThinkingHome/device_sentinel.git w1
#   cd w1 && ./tools/setup_container.sh
#
# It is safe to run again. An environment that already exists at the
# right version is left alone, so a second run costs seconds.
#
# Fleet data is separate and private. Unzip the test-data archive and
# point DEVICE_SENTINEL_FLEET_DIR at its fleets folder; this script
# reports whether it found one but never creates or fetches it.

set -uo pipefail

PREFIX="${DEVICE_SENTINEL_ENV_PREFIX:-/home/claude}"
FLEETS="${DEVICE_SENTINEL_FLEET_DIR:-$PREFIX/fleets}"
TREE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHON_VERSION="3.14.6"
UV_VERSION="0.12.17"
UV="/usr/local/bin/uv"
RUFF_PIN="0.15.22"
BANDIT_PIN="1.9.4"
MYPY_PIN="2.3.1"

FLOOR_ENV="$PREFIX/venv_329"     # Home Assistant 2026.5.0, the declared minimum
CURRENT_ENV="$PREFIX/venv_365"   # Home Assistant 2026.9.2, what the fleets run
TOOLS_ENV="$PREFIX/venv_tools"   # ruff and bandit, pinned
JSDOM_DIR="$PREFIX/jsdom"        # the front end's only harness

say() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
die() { printf '\nSTOPPED: %s\n' "$*" >&2; exit 1; }

cd "$TREE" || die "cannot reach the repository root"
[ -f requirements_test.txt ] || die "requirements_test.txt is not here; run this from the repository root"
[ -f requirements_test_floor.txt ] || die "requirements_test_floor.txt is not here"

# ------------------------------------------------------------------ uv
#
# The container ships a uv in ~/.local/bin that comes first on the path
# and cannot find Python 3.14.6: `uv python install 3.14.6` answers "no
# download found for request". A current uv installed to /usr/local/bin
# takes precedence and knows it. Calling uv by its full path everywhere
# below is deliberate, so the older one on the path can never be used
# by accident.

say "uv"
if [ -x "$UV" ] && "$UV" --version 2>/dev/null | grep -qv " 0\.11\."; then
  note "already here: $("$UV" --version)"
else
  ARCHIVE="uv-x86_64-unknown-linux-gnu.tar.gz"
  URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${ARCHIVE}"
  TMP="$(mktemp -d)"
  curl -sSL -o "$TMP/$ARCHIVE" "$URL" || die "cannot download uv from $URL"
  tar xzf "$TMP/$ARCHIVE" -C "$TMP" || die "cannot unpack uv"
  cp "$TMP"/uv-x86_64-unknown-linux-gnu/uv "$TMP"/uv-x86_64-unknown-linux-gnu/uvx /usr/local/bin/ \
    || die "cannot install uv to /usr/local/bin"
  rm -rf "$TMP"
  note "installed: $("$UV" --version)"
fi

# ------------------------------------------------------- the harnesses
#
# Two, until the declared minimum reaches 2026.8.0. The floor harness is
# the only one on which a device can belong to two config entries, which
# Home Assistant stopped allowing in 2026.8, and it retires with the two
# tests that need it.
#
# Never uninstall a package from a harness environment. Home Assistant
# 2026.9.2 itself requires probatio==0.11.4, and removing it to satisfy
# something else takes the harness down.

build_env() {  # $1 path  $2 label  $3.. install arguments
  local path="$1" label="$2"; shift 2
  if [ -x "$path/bin/python" ]; then
    note "$label already built"
  else
    "$UV" venv --python "$PYTHON_VERSION" "$path" >/dev/null 2>&1 \
      || die "cannot create $label at $path on Python $PYTHON_VERSION"
  fi
  "$UV" pip install --quiet --python "$path/bin/python" "$@" \
    || die "cannot install into $label"
}

say "harness at the declared minimum (2026.5.0)"
build_env "$FLOOR_ENV" "venv_329" -r requirements_test_floor.txt
note "$("$FLOOR_ENV/bin/python" -c 'from homeassistant.const import __version__ as v; import sys; print("Home Assistant", v, "on Python", sys.version.split()[0])')"

say "harness at what the fleets run (2026.9.2)"
# mypy goes in beside the harness rather than with the other linters,
# so it type-checks against the same Home Assistant the fleets run.
build_env "$CURRENT_ENV" "venv_365" -r requirements_test.txt "mypy==$MYPY_PIN"
note "$("$CURRENT_ENV/bin/python" -c 'from homeassistant.const import __version__ as v; import sys; print("Home Assistant", v, "on Python", sys.version.split()[0])')"

# ------------------------------------------------------------- linters
#
# ruff is pinned. Unpinned, 0.16 reports 135 findings this tree does not
# carry, and a release is judged on whether it adds findings rather than
# on a clean bill, so an unpinned ruff makes that comparison meaningless.

say "linters"
build_env "$TOOLS_ENV" "venv_tools" "ruff==$RUFF_PIN" "bandit==$BANDIT_PIN"
note "$("$TOOLS_ENV/bin/ruff" --version)"
note "bandit $("$TOOLS_ENV/bin/bandit" --version 2>&1 | head -1 | awk '{print $2}')"
note "$("$CURRENT_ENV/bin/mypy" --version)"

# ---------------------------------------------------------- the browser
#
# The build gate cannot test JavaScript. panel.js is checked in a
# simulated browser instead: drive it with a stubbed hass.callWS, paint
# each tab, and assert on what it draws.

say "simulated browser"
mkdir -p "$JSDOM_DIR"
if [ -d "$JSDOM_DIR/node_modules/jsdom" ]; then
  note "jsdom already installed"
else
  ( cd "$JSDOM_DIR" && npm install --silent jsdom >/dev/null 2>&1 ) \
    || die "cannot install jsdom in $JSDOM_DIR"
fi
( cd "$JSDOM_DIR" && node -e "require('jsdom')" ) \
  || die "jsdom is installed but will not load"
note "jsdom loads, on $(node --version)"

# ------------------------------------------------------------- the gate
#
# Six runs: the suite twice with fleet files on each harness, and once
# without on each, then the three scanners. One line per run in the
# summary file.
#
# Two gates must never run at once. A second run starves the first and
# tests fail on their 120 second limit rather than on their merits, which
# reads as a broken tree and is not one. The script refuses to start
# beside a run that is already going.

say "gate script"
cat > "$PREFIX/gate.sh" <<GATE
#!/usr/bin/env bash
# Written by tools/setup_container.sh. Run it detached:
#   cd $PREFIX && setsid nohup ./gate.sh >/dev/null 2>&1 < /dev/null &
TREE="\${1:-$TREE}"
SUM="$PREFIX/gate_summary.txt"
FLEETS="$FLEETS"
cd "\$TREE" || exit 1

# Count python processes running pytest, not every command line that
# happens to mention it. A shell invoking the gate carries the words in
# its own arguments and would otherwise look like a run in progress.
running=\$(ps -eo comm,args | awk '\$1 ~ /^python/ && /-m pytest/ {n++} END {print n+0}')
if [ "\$running" -gt 0 ]; then
  echo "a suite run is already going; stop it by process number first" >&2
  ps -eo pid,etimes,comm,args | awk '\$3 ~ /^python/ && /-m pytest/' >&2
  exit 1
fi

# tests/conftest.py falls back to a default path when
# DEVICE_SENTINEL_FLEET_DIR is unset, so leaving it unset does not mean
# "no fleets"; it means "whatever is at the default path". The runs that
# prove what GitHub proves point at an empty directory instead.
NOFLEET=\$(mktemp -d)
trap 'rm -rf "\$NOFLEET"' EXIT

echo "=== gate start \$(date -u) tree=\$TREE ===" >> "\$SUM"
run() {  # \$1 label  \$2 python  \$3 fleet directory
  local label="\$1" py="\$2" fleet="\$3" out start rc el
  out=\$(mktemp); start=\$SECONDS
  DEVICE_SENTINEL_FLEET_DIR="\$fleet" "\$py" -m pytest tests -q -p no:sugar -rfExXs --timeout=120 > "\$out" 2>&1
  rc=\$?; el=\$((SECONDS-start))
  # pytest prints the short summary first and the counts last, so the
  # final line is the one to keep.
  echo "\$label rc=\$rc \${el}s :: \$(tail -1 "\$out")" >> "\$SUM"
  cp "\$out" "$PREFIX/gate_\${label}.log"; rm -f "\$out"
}
run floor_fleet_1   $FLOOR_ENV/bin/python   "\$FLEETS"
run floor_fleet_2   $FLOOR_ENV/bin/python   "\$FLEETS"
run current_fleet_1 $CURRENT_ENV/bin/python "\$FLEETS"
run current_fleet_2 $CURRENT_ENV/bin/python "\$FLEETS"
run floor_nofleet   $FLOOR_ENV/bin/python   "\$NOFLEET"
run current_nofleet $CURRENT_ENV/bin/python "\$NOFLEET"
{
  printf 'ruff: ';   $TOOLS_ENV/bin/ruff check custom_components/ tests/ 2>&1 | tail -1
  printf 'bandit issues: '; $TOOLS_ENV/bin/bandit -q -r custom_components 2>&1 | grep -c "Issue:"
  printf 'mypy outside the mixin pattern: '; $CURRENT_ENV/bin/mypy custom_components/device_sentinel 2>&1 | grep "error:" | grep -v attr-defined | wc -l
  printf 'mypy total: ';    $CURRENT_ENV/bin/mypy custom_components/device_sentinel 2>&1 | grep -c "error:"
  echo "=== gate done \$(date -u) ==="
} >> "\$SUM"
GATE
chmod +x "$PREFIX/gate.sh"
note "written to $PREFIX/gate.sh"

# ---------------------------------------------------------- fleet data
#
# Private, and never in this repository. It arrives as the test-data
# archive; its MANIFEST.md says which file belongs to which house.

say "fleet data"
if [ -d "$FLEETS" ]; then
  for house in "$FLEETS"/*/; do
    [ -d "$house" ] || continue
    note "$(basename "$house"): $(find "$house" -maxdepth 1 -type f | wc -l) file(s)"
  done
else
  note "none found at $FLEETS"
  note "unzip the test-data archive and move its fleets folder there,"
  note "or set DEVICE_SENTINEL_FLEET_DIR. Without it every fleet case skips."
fi

cat <<DONE

== ready

  the suite   DEVICE_SENTINEL_FLEET_DIR=$FLEETS \\
                $CURRENT_ENV/bin/python -m pytest tests -q -p no:sugar -rfExXs --timeout=120
  the gate    cd $PREFIX && setsid nohup ./gate.sh >/dev/null 2>&1 < /dev/null &
              then read $PREFIX/gate_summary.txt

Main__Project.md under Test Baseline carries the counts a clean tree
should give, and is the reference for every gate.
DONE
