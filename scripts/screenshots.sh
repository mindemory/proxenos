#!/bin/bash
# Retake the README's pictures (docs/images): Home, Care, Errands, Drafts and Tasks at desktop and
# phone width. They show only the made-up vault `proxenos demo` writes: the page runs on it alone,
# on the demo's port (never 4747), with no way to run the proxenos command from a button, and
# Chrome runs headless on a throwaway profile. Everything is removed again afterwards.
#
# Needs the proxenos conda env, the web packages (npm --prefix web install), Google Chrome (or
# CHROME=<its binary>) and a Python with Pillow (python3, or PYTHON=<another>) to shrink the
# pictures; zopflipng on the PATH shrinks them further. Open every one before committing it.
#
#   scripts/screenshots.sh         into docs/images
#   scripts/screenshots.sh DIR     into DIR instead
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd -P)"
prog="screenshots"
# shellcheck source=scripts/lib.sh
source "$repo/scripts/lib.sh"
out="${1:-$repo/docs/images}"
chrome="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
python="${PYTHON:-python3}"
debug_port=9339

# Python in the conda env, on this checkout's code (the env's install may point at another).
in_env() {
  # shellcheck disable=SC2016 # $1 to $4 are expanded by the inner bash
  bash -c 'source "$1" && conda activate "$2" && PYTHONPATH="$3" exec python -c "$4" "${@:5}"' \
    _ "$conda_sh" "$conda_env" "$repo/src" "$@"
}

find_conda_env
[ -x "$chrome" ] || fail "no Chrome at $chrome. Install Google Chrome, or set CHROME to its binary."
"$python" -c "import PIL" 2>/dev/null || fail "$python has no Pillow: pip install pillow, or set PYTHON."
[ -d "$repo/web/node_modules" ] || fail "the web packages aren't installed: npm --prefix web install"
read -r port name <<<"$(in_env 'from proxenos import demo; print(demo.PORT, demo.NAME)')"
[ -n "$name" ] || fail "couldn't read the demo's port and name from $repo/src/proxenos/demo.py."
if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
  fail "something is already serving on port $port. Stop it, then run this again."
fi

work="$(mktemp -d)"
pids=()
cleanup() {
  [ ${#pids[@]} -eq 0 ] || kill "${pids[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
  rm -rf "$work"
}
trap cleanup EXIT

echo "Writing the demo vault..."
in_env 'import sys; from proxenos import cli; cli.main(sys.argv[1:])' demo "$work/vault" >/dev/null

echo "Starting the page on it, on port $port..."
(
  cd "$repo/web"
  PROXENOS_VAULT="$work/vault" PROXENOS_NAME="$name" PROXENOS_BIN=/usr/bin/false \
    exec ./node_modules/.bin/next dev -H 127.0.0.1 -p "$port"
) >"$work/page.log" 2>&1 &
pids+=($!)
"$chrome" --headless=new --remote-debugging-address=127.0.0.1 --remote-debugging-port="$debug_port" \
  --user-data-dir="$work/chrome" --no-first-run --no-default-browser-check --hide-scrollbars \
  --disable-extensions --disable-sync --disable-background-networking about:blank \
  >"$work/chrome.log" 2>&1 &
pids+=($!)
for _ in $(seq 240); do
  curl -sf -o /dev/null "http://127.0.0.1:$port/app" &&
    curl -sf -o /dev/null "http://127.0.0.1:$debug_port/json/version" && break
  sleep 0.5
done
curl -sf -o /dev/null "http://127.0.0.1:$port/app" ||
  fail "the page didn't start: $(tail -n 5 "$work/page.log")"
curl -sf -o /dev/null "http://127.0.0.1:$debug_port/json/version" ||
  fail "Chrome didn't start: $(tail -n 5 "$work/chrome.log")"

echo "Taking the pictures..."
node "$repo/scripts/screenshots.mjs" "http://127.0.0.1:$port" "$debug_port" "$work/shots" >/dev/null
"$python" "$repo/scripts/shrink-png.py" "$work/shots" "$out"
echo "Open each one before committing it: only the demo's made-up records should be in them."
