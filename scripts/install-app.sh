#!/bin/bash
# Keep Proxenos running in the background from login on, with no terminal open: two launchd jobs
# in ~/Library/LaunchAgents. local.proxenos.web serves a production build of the page on
# 127.0.0.1:4747 and is restarted if it stops; local.proxenos.sync runs `proxenos sync` every 15
# minutes (and once on wake, if the Mac slept through one). Their output is appended to
# <vault>/logs/web.log and sync.log. Running this again rebuilds the page and restarts both, so
# run it after the code changes.
#
#   scripts/install-app.sh                                  install, or rebuild and restart
#   launchctl kickstart gui/$(id -u)/local.proxenos.sync    sync now
#   launchctl bootout gui/$(id -u)/local.proxenos.web       stop the page until the next install
#   launchctl bootout gui/$(id -u)/local.proxenos.sync      stop syncing until the next install
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd -P)"
prog="install-app"
# shellcheck source=scripts/lib.sh
source "$repo/scripts/lib.sh"
web="$repo/web"
port=4747

refuse_worktree
find_conda_env
find_logs

# Another server on the port (a `proxenos web` window, say) would keep the job's from starting.
stop_job local.proxenos.web
if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
  fail "something else is serving on port $port (a \`proxenos web\` window?). Stop it, then run this again."
fi

echo "Building the page (a minute or two)..."
[ -d "$web/node_modules" ] || npm --prefix "$web" install
npm --prefix "$web" run build >"$logs/web-build.log" 2>&1 ||
  fail "the page didn't build; see $logs/web-build.log"

install_job local.proxenos.web "$web" "./node_modules/.bin/next start -H 127.0.0.1 -p $port" \
  "$logs/web.log" '  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>'
install_job local.proxenos.sync "$HOME" "proxenos sync" "$logs/sync.log" '  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>900</integer>'

echo "Proxenos runs at http://127.0.0.1:$port and syncs every 15 minutes, from login on."
echo "Logs: $logs/web.log and $logs/sync.log."
