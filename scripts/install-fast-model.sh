#!/bin/bash
# Keep the fast model's server running from login on: a launchd job in ~/Library/LaunchAgents,
# local.proxenos.fastmodel, that runs `proxenos model serve-fast` (mlx-lm's server with
# mlx-community/gemma-4-e4b-it-4bit, 5 GB) on 127.0.0.1:8898 and restarts it if it stops. The
# light background jobs (the task list, the network, the notes, ...) use it once
# PROXENOS_FAST_MODEL names it, which Settings or setup does where the Mac has mlx-lm and the
# model downloaded. Its output is appended to <vault>/logs/fast-model.log. The first start
# downloads the weights from Hugging Face; nothing else leaves the computer. Running this again
# restarts the job.
#
# It needs a Mac with Apple silicon and mlx-lm in the proxenos conda env (pip install mlx-lm).
#
#   scripts/install-fast-model.sh                              install or restart the job
#   proxenos model bench                                       time it against the main model
#   launchctl bootout gui/$(id -u)/local.proxenos.fastmodel    stop it until the next install
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd -P)"
prog="install-fast-model"
# shellcheck source=scripts/lib.sh
source "$repo/scripts/lib.sh"
label="local.proxenos.fastmodel"

[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] ||
  fail "the fast model is served with mlx-lm, which needs a Mac with Apple silicon."
refuse_worktree
find_conda_env
find_logs
# shellcheck disable=SC2016 # $1 and $2 are expanded by the inner bash
bash -c 'source "$1" && conda activate "$2" && python -c "import mlx_lm"' _ "$conda_sh" "$conda_env" \
  >/dev/null 2>&1 ||
  fail "mlx-lm isn't installed in the $conda_env conda env. Run: conda activate $conda_env && pip install mlx-lm"

# From the home folder, as the other jobs: a repo under ~/Documents is a folder macOS protects.
install_job "$label" "$HOME" "proxenos model serve-fast" "$logs/fast-model.log" '  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>' Interactive

echo "Installed $label: the fast model is served at http://127.0.0.1:8898/v1 from login on."
echo "Log: $logs/fast-model.log (the first start downloads the model, so give it a few minutes)."
echo "Light jobs use it once Settings, under Model, shows it set, or PROXENOS_FAST_MODEL=local:mlx-community/gemma-4-e4b-it-4bit."
