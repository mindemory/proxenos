#!/bin/bash
# Run `proxenos night` at 01:30 every day: a launchd job in ~/Library/LaunchAgents that activates
# the proxenos conda env and runs the master and every clone, with its output appended to
# <vault>/logs/night.log. Running this again rewrites the job and reloads it. A job installed
# under the project's earlier label is stopped and removed, so only one runs.
#
# It refuses to install without a model: a local one (PROXENOS_MODEL=ollama:<name> in .env) or
# ANTHROPIC_API_KEY. Every step after the sync needs one, so a night without would only sync.
#
#   scripts/install-night.sh                                 install or update the job
#   launchctl kickstart gui/$(id -u)/local.proxenos.night    run it once, now
#   launchctl bootout gui/$(id -u)/local.proxenos.night      stop it until the next install
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd -P)"
prog="install-night"
# shellcheck source=scripts/lib.sh
source "$repo/scripts/lib.sh"
label="local.proxenos.night"
# The label before the rename.
old_label="local.digital-twin.night"

case "$(env_value PROXENOS_MODEL)" in
  ollama:*) ;;
  *)
    [ -n "$(env_value ANTHROPIC_API_KEY)" ] ||
      fail "$env_file names no model (PROXENOS_MODEL=ollama:<name>, or ANTHROPIC_API_KEY), so a night run could only sync."
    ;;
esac
find_conda_env
find_logs

# The job under the old label: stopped, and its file removed so it doesn't come back at login.
old_plist="$HOME/Library/LaunchAgents/$old_label.plist"
if launchctl print "$domain/$old_label" >/dev/null 2>&1 || [ -f "$old_plist" ]; then
  stop_job "$old_label"
  rm -f "$old_plist"
  echo "Removed the old $old_label job."
fi

install_job "$label" "$repo" "proxenos night" "$logs/night.log" '  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>1</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>'

echo "Installed $label: proxenos night runs at 01:30 every day (on wake, if the Mac was asleep)."
echo "Log: $logs/night.log. Run it now: launchctl kickstart $domain/$label"
echo "If the log says \"Operation not permitted\", macOS is keeping the job out of a protected"
echo "folder (this repo is under ~/Documents); allow it in System Settings > Privacy & Security."
