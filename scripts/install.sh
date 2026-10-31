#!/bin/bash
# Set Proxenos up on a Mac in one command, from a fresh clone: what the README's Quick start does
# by hand. It installs what's missing with Homebrew (Node, Ollama, and Miniforge when there's no
# conda), creates the `proxenos` conda env and installs the package into it, installs the page's
# packages, starts Ollama and pulls a local model that fits this Mac's memory. Running it again
# skips whatever is already there.
#
#   scripts/install.sh                     set up, then `conda activate proxenos && proxenos web`
#   scripts/install.sh --no-model          skip the model downloads (use a hosted model instead)
#   scripts/install.sh --start-at-login    also keep the page and a sync running from login on
#
# It needs Homebrew (brew.sh) and asks for nothing else. Nothing personal is read or written: the
# vault, your name and a model are picked on the page's first-run setup.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd -P)"
prog="install"
# shellcheck source=scripts/lib.sh
source "$repo/scripts/lib.sh"
env_name="${PROXENOS_ENV:-proxenos}" # another name only to try the script beside a working env
model=1
login=0
for arg in "$@"; do
  case "$arg" in
    --no-model) model=0 ;;
    --start-at-login) login=1 ;;
    -h | --help)
      sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) fail "unknown option $arg (try --help)" ;;
  esac
done

step() { printf '\n==> %s\n' "$*"; }

[ "$(uname -s)" = Darwin ] || fail "this script is for macOS. On Windows or Linux, follow docs/apps.md."
[ "$(uname -m)" = arm64 ] || echo "$prog: an Intel Mac works, but local models are slow on it; a hosted model may suit it better."
command -v brew >/dev/null || fail 'Homebrew is needed first: see https://brew.sh, then run this again.'

step "Tools: Node and Ollama"
for tool in node ollama; do
  if command -v "$tool" >/dev/null; then
    echo "$tool: already installed"
  else
    brew install "$tool"
  fi
done

step "Python: the $env_name conda env"
if [ ! -f "$conda_sh" ]; then
  brew install --cask miniforge
  conda_sh="$(find_conda_sh)"
  [ -f "$conda_sh" ] || fail "Miniforge installed but its conda wasn't found. Set CONDA_SH and run this again."
fi
set +u # conda's activation scripts read unset variables
# shellcheck disable=SC1090 # conda's own activation script
source "$conda_sh"
if conda env list | awk '{print $1}' | grep -qx "$env_name"; then
  echo "$env_name: already there"
else
  # Native arm64 on purpose, as environment.yml explains.
  CONDA_SUBDIR=osx-arm64 conda env create -q -n "$env_name" -f "$repo/environment.yml"
fi
conda activate "$env_name"
set -u
conda config --env --set subdir osx-arm64 >/dev/null 2>&1 || true
python -m pip install -q -e "$repo"
command -v proxenos >/dev/null || fail "the proxenos command didn't install; see the pip output above."

step "The page's packages"
if [ -d "$repo/web/node_modules" ]; then
  echo "web/node_modules: already there"
else
  npm --prefix "$repo/web" ci --no-audit --no-fund
fi

if [ "$model" = 1 ]; then
  step "A local model, through Ollama"
  brew services start ollama >/dev/null 2>&1 || true
  for _ in $(seq 30); do
    ollama list >/dev/null 2>&1 && break
    sleep 1
  done
  gb=$(($(sysctl -n hw.memsize) / 1024 / 1024 / 1024))
  if [ "$gb" -ge 32 ]; then
    ollama pull gemma4:26b
  else
    echo "This Mac has ${gb} GB of memory; gemma4:26b needs about 32. Pick a smaller model on the"
    echo "setup page (any you pull with 'ollama pull NAME' is listed there), or use an API key."
  fi
  ollama pull qwen3-embedding:0.6b # search by meaning; small
fi

if [ "$login" = 1 ]; then
  step "Keep it running from login on"
  [ "$env_name" = proxenos ] || fail "--start-at-login needs the env named proxenos."
  "$repo/scripts/install-app.sh"
fi

step "Done"
echo "Open Proxenos:   conda activate $env_name && proxenos web"
echo "Try it first on made-up records, with no model:   conda activate $env_name && proxenos demo"
echo "The page asks your name, where to keep the vault and which model, then helps you connect a first source."
