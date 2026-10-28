#!/bin/bash
# Run `proxenos night` at 01:30 every day: a launchd job in ~/Library/LaunchAgents that activates
# the proxenos conda env and runs the master and every clone, with its output appended to
# <vault>/logs/night.log. Running this again rewrites the job and reloads it. A job installed
# under the project's earlier label is stopped and removed, so only one runs.
#
# It refuses to install without ANTHROPIC_API_KEY in .env: every step after the sync needs
# the model, so a night without a key would only sync.
#
#   scripts/install-night.sh                                 install or update the job
#   launchctl kickstart gui/$(id -u)/local.proxenos.night    run it once, now
#   launchctl bootout gui/$(id -u)/local.proxenos.night      stop it until the next install
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd -P)"
env_file="$repo/.env"
label="local.proxenos.night"
# The label before the rename.
old_label="local.digital-twin.night"
plist="$HOME/Library/LaunchAgents/$label.plist"
conda_sh="${CONDA_SH:-/opt/anaconda3/etc/profile.d/conda.sh}"
domain="gui/$(id -u)"

fail() {
  echo "install-night: $*" >&2
  exit 1
}

# One key's value in .env, without quotes or a trailing comment. Empty when it isn't set.
env_value() {
  [ -f "$env_file" ] || return 0
  sed -n -E "s/^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=[[:space:]]*//p" "$env_file" |
    tail -n 1 |
    sed -E -e 's/^"([^"]*)".*$/\1/' -e t -e "s/^'([^']*)'.*\$/\\1/" -e t \
      -e 's/[[:space:]]+#.*$//' -e 's/[[:space:]]+$//'
}

# Text as it may sit inside a plist <string>.
xml() {
  printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

[ -n "$(env_value ANTHROPIC_API_KEY)" ] ||
  fail "$env_file has no ANTHROPIC_API_KEY, so a night run could only sync. Add the key and run this again."
[ -f "$conda_sh" ] || fail "no conda at $conda_sh. Set CONDA_SH to conda's etc/profile.d/conda.sh."
# The env is "proxenos"; one set up before the rename still has its old name.
conda_env=""
for candidate in proxenos digital_twin; do
  # shellcheck disable=SC2016 # $1 and $2 are expanded by the inner bash
  if bash -c 'source "$1" && conda activate "$2" && command -v proxenos' _ "$conda_sh" "$candidate" >/dev/null 2>&1; then
    conda_env="$candidate"
    break
  fi
done
[ -n "$conda_env" ] ||
  fail "no conda env has the proxenos command. Set it up as the README says, then run this again."

vault="$(env_value PROXENOS_VAULT)"
vault="${vault:-$(env_value TWIN_VAULT)}"
vault="${vault:-$HOME/proxenos_vault}"
case "$vault" in
  "~") vault="$HOME" ;;
  "~/"*) vault="$HOME/${vault#"~/"}" ;;
esac
logs="$vault/logs"
mkdir -p "$logs"
chmod 700 "$logs"

# Stop the job if an earlier install loaded it, and wait until launchd lets go of it.
stop_job() {
  launchctl bootout "$domain/$1" 2>/dev/null || true
  for _ in $(seq 50); do
    launchctl print "$domain/$1" >/dev/null 2>&1 || break
    sleep 0.1
  done
}
stop_job "$label"

# The job under the old label: stopped, and its file removed so it doesn't come back at login.
old_plist="$HOME/Library/LaunchAgents/$old_label.plist"
if launchctl print "$domain/$old_label" >/dev/null 2>&1 || [ -f "$old_plist" ]; then
  stop_job "$old_label"
  rm -f "$old_plist"
  echo "Removed the old $old_label job."
fi

mkdir -p "$(dirname "$plist")"
tmp="$(mktemp "$plist.XXXXXX")"
cat >"$tmp" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>source "\$1" &amp;&amp; conda activate "\$2" &amp;&amp; exec proxenos night</string>
    <string>proxenos-night</string>
    <string>$(xml "$conda_sh")</string>
    <string>$(xml "$conda_env")</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$(xml "$repo")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>1</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$(xml "$logs/night.log")</string>
  <key>StandardErrorPath</key>
  <string>$(xml "$logs/night.log")</string>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
PLIST
chmod 644 "$tmp"
plutil -lint -s "$tmp" || {
  rm -f "$tmp"
  fail "the job file came out malformed; nothing was installed."
}
mv -f "$tmp" "$plist"

launchctl bootstrap "$domain" "$plist"
launchctl enable "$domain/$label"

echo "Installed $label: proxenos night runs at 01:30 every day (on wake, if the Mac was asleep)."
echo "Log: $logs/night.log. Run it now: launchctl kickstart $domain/$label"
echo "If the log says \"Operation not permitted\", macOS is keeping the job out of a protected"
echo "folder (this repo is under ~/Documents); allow it in System Settings > Privacy & Security."
