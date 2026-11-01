#!/bin/bash
# Try the built app's own parts without opening it, after desktop/build.sh: its Python writes a
# made-up vault (`proxenos demo`), its page's server starts on that vault, and two routes answer:
# /api/status, the page reading the vault, and /api/connect, the page running the app's Python.
# Everything it uses (the vault, a home folder for settings) is in a new temporary folder, so
# neither touches yours, and it's removed at the end. Usage: desktop/smoke.sh [PORT]
set -euo pipefail

desktop="$(cd "$(dirname "$0")" && pwd -P)"
port="${1:-4870}"
case "$(uname -s)" in
  Darwin)
    resources="$desktop/dist/mac-arm64/Proxenos.app/Contents/Resources"
    python="$resources/python/bin/python3"
    ;;
  MINGW* | MSYS*)
    resources="$desktop/dist/win-unpacked/resources"
    python="$resources/python/python.exe"
    ;;
  *)
    echo "smoke: no app built for $(uname -s)" >&2
    exit 1
    ;;
esac
# Windows programs want Windows paths in their environment.
native() { if command -v cygpath >/dev/null; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

work="$(mktemp -d)"
server=""
cleanup() {
  local status=$?
  if [ -n "$server" ]; then
    kill "$server" 2>/dev/null || true
    wait "$server" 2>/dev/null || true
  fi
  rm -rf "$work"
  exit "$status"
}
trap cleanup EXIT
mkdir -p "$work/home"
export HOME="$work/home" USERPROFILE="$(native "$work/home")" APPDATA="$(native "$work/home")"
export PROXENOS_VAULT="$(native "$work/vault")" PROXENOS_NAME="Joe Bloggs" PYTHONUTF8=1

"$python" -m proxenos demo "$PROXENOS_VAULT" | head -1

PROXENOS_HOME="$(native "$resources")" PROXENOS_PYTHON="$(native "$python")" PROXENOS_PORT="$port" \
  HOSTNAME=127.0.0.1 PORT="$port" NEXT_TELEMETRY_DISABLED=1 \
  node "$(native "$resources/web/server.js")" >"$work/server.log" 2>&1 &
server=$!

answer() { curl -s -o "$work/answer.json" -w '%{http_code}' "http://127.0.0.1:$port$1" || true; }
for _ in $(seq 60); do
  [ "$(answer /api/status)" = 200 ] && break
  sleep 1
done
code="$(answer /api/status)"
echo "smoke: /api/status $code"
if [ "$code" != 200 ]; then
  cat "$work/server.log" >&2
  exit 1
fi
code="$(answer /api/connect)"
echo "smoke: /api/connect $code"
if [ "$code" != 200 ] || ! grep -q '"error":null' "$work/answer.json"; then
  head -c 600 "$work/answer.json" >&2
  exit 1
fi
echo "smoke: ok"
