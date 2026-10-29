# Shared by the install scripts: reading .env, finding the conda env and the vault, and writing
# and loading a launchd job that runs one command in the env. Sourced, not run; the script that
# sources it sets `prog` (its name, for messages) and `repo` first.

env_file="$repo/.env"
conda_sh="${CONDA_SH:-/opt/anaconda3/etc/profile.d/conda.sh}"
domain="gui/$(id -u)"

fail() {
  echo "$prog: $*" >&2
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

# The conda env with the proxenos command: "proxenos", or one set up before the rename.
find_conda_env() {
  [ -f "$conda_sh" ] || fail "no conda at $conda_sh. Set CONDA_SH to conda's etc/profile.d/conda.sh."
  for candidate in proxenos digital_twin; do
    # shellcheck disable=SC2016 # $1 and $2 are expanded by the inner bash
    if bash -c 'source "$1" && conda activate "$2" && command -v proxenos' _ "$conda_sh" "$candidate" >/dev/null 2>&1; then
      conda_env="$candidate"
      return
    fi
  done
  fail "no conda env has the proxenos command. Set it up as the README says, then run this again."
}

# The vault's logs folder, made private.
find_logs() {
  local vault
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
}

# Stop a job if an earlier install loaded it, and wait until launchd lets go of it.
stop_job() {
  launchctl bootout "$domain/$1" 2>/dev/null || true
  for _ in $(seq 50); do
    launchctl print "$domain/$1" >/dev/null 2>&1 || break
    sleep 0.1
  done
}

# install_job LABEL DIR COMMAND LOG WHEN: run COMMAND in the conda env, from DIR, with its output
# appended to LOG; WHEN is the plist keys that say when it runs. Replaces any earlier copy.
install_job() {
  local label="$1" dir="$2" command="$3" log="$4" when="$5"
  local plist="$HOME/Library/LaunchAgents/$label.plist" tmp
  stop_job "$label"
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
    <string>source "\$1" &amp;&amp; conda activate "\$2" &amp;&amp; exec $(xml "$command")</string>
    <string>$label</string>
    <string>$(xml "$conda_sh")</string>
    <string>$(xml "$conda_env")</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$(xml "$dir")</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
$when
  <key>StandardOutPath</key>
  <string>$(xml "$log")</string>
  <key>StandardErrorPath</key>
  <string>$(xml "$log")</string>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
PLIST
  chmod 644 "$tmp"
  plutil -lint -s "$tmp" || {
    rm -f "$tmp"
    fail "the job file for $label came out malformed; nothing was installed."
  }
  mv -f "$tmp" "$plist"
  launchctl bootstrap "$domain" "$plist"
  launchctl enable "$domain/$label"
}
