#!/bin/bash
# Build the desktop app (desktop/main.js): Electron around the page, built as a Next.js standalone
# server, and a Python of its own with Proxenos installed. From a checkout, on the computer it's
# for: a .dmg and a .zip on a Mac with Apple silicon, a per-user installer (NSIS) on Windows x64
# under Git Bash. Needs git, curl, tar, Node 22.12 or newer and npm. The installers land in
# desktop/dist, unsigned: electron-builder.config.js says where signing goes.
#
# What it downloads, all while building and nothing when the app runs: npm packages from the
# lockfiles, Proxenos's Python packages from PyPI, and CPython itself, a pinned
# python-build-standalone 3.12 from its official GitHub releases
# (github.com/astral-sh/python-build-standalone), checked against the SHA-256 written below before
# it's unpacked. The archive is kept in desktop/.cache for the next build.
#
# The page and the wheel are built from a copy of the checkout's tracked files, so nothing
# untracked (an .env, say) goes into the app, and web/.next, which a running page may be serving,
# is never touched.
set -euo pipefail

desktop="$(cd "$(dirname "$0")" && pwd -P)"
repo="$(dirname "$desktop")"
cache="$desktop/.cache"    # the Python archive, the copied sources and the wheel
stage="$desktop/resources" # what goes into the app beside main.js: python/, web/ and icon.png

# CPython 3.12.16, install_only_stripped, from python-build-standalone's release 20261026.
release=20261026
version=3.12.16
case "$(uname -s)/$(uname -m)" in
  Darwin/arm64)
    triple=aarch64-apple-darwin
    sha256=353d5f1b4fd2715e7053f12f068435d5bbad16b91e057006b5d01e0925709a7e
    python=python/bin/python3
    platform=(--mac --arm64)
    ;;
  MINGW64*/x86_64 | MSYS*/x86_64)
    triple=x86_64-pc-windows-msvc
    sha256=1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149
    python=python/python.exe
    platform=(--win --x64)
    ;;
  *)
    echo "build: only macOS on Apple silicon and Windows x64 for now, not $(uname -s) $(uname -m)" >&2
    exit 1
    ;;
esac

say() { echo "build: $*"; }
sha() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }

# Telemetry off, and a Python that reads only its own packages.
export NEXT_TELEMETRY_DISABLED=1 PYTHONNOUSERSITE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
unset PYTHONPATH PYTHONHOME

say "copying the checkout's tracked files"
rm -rf "$cache/src"
mkdir -p "$cache/src" "$stage"
git -C "$repo" ls-files -z -- pyproject.toml LICENSE src web |
  tar -C "$repo" --null -T - -cf - | tar -C "$cache/src" -xf -

archive="cpython-$version+$release-$triple-install_only_stripped.tar.gz"
if [ ! -f "$cache/$archive" ] || [ "$(sha "$cache/$archive")" != "$sha256" ]; then
  say "downloading $archive"
  curl -fL --retry 3 --proto '=https' -o "$cache/$archive.part" \
    "https://github.com/astral-sh/python-build-standalone/releases/download/$release/${archive/+/%2B}"
  mv "$cache/$archive.part" "$cache/$archive"
fi
got="$(sha "$cache/$archive")"
if [ "$got" != "$sha256" ]; then
  rm -f "$cache/$archive"
  echo "build: $archive has SHA-256 $got, not $sha256; it was removed" >&2
  exit 1
fi
say "unpacking Python $version"
rm -rf "$stage/python"
tar -xzf "$cache/$archive" -C "$stage"

say "installing Proxenos into it"
rm -rf "$cache/wheel"
"$stage/$python" -m pip wheel --quiet --no-deps --wheel-dir "$cache/wheel" "$cache/src"
"$stage/$python" -m pip install --quiet --only-binary=:all: --no-warn-script-location \
  "$cache"/wheel/proxenos-*.whl
"$stage/$python" -m proxenos --help >/dev/null

# Google sign-in that ships with the app: the builder's own Google client (a Desktop app one from
# Google Cloud), so nobody who gets the app makes a project of their own. From GOOGLE_CLIENT_ID and
# GOOGLE_CLIENT_SECRET in this build's environment, else (on a Mac) the builder's own Proxenos:
# the repo's .env, its settings file or its Keychain, read through the staged Python's
# proxenos.config. It goes to resources/client/google.json in Google's own download format, which
# main.js hands the app as PROXENOS_GOOGLE_CLIENT. Neither value is ever printed. An installed
# app's client secret isn't confidential (Google says so), but it isn't committed anywhere either.
rm -rf "$stage/client"
mkdir -p "$stage/client"
if "$stage/$python" -I -c '
import json, os, sys
from pathlib import Path

names = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
if not all(os.environ.get(n) for n in names):
    env = Path(sys.argv[2]) / ".env"
    if sys.platform == "darwin":
        from dotenv import dotenv_values
        from proxenos import config

        for n, v in (dotenv_values(env) if env.is_file() else {}).items():
            if n in names and v and not os.environ.get(n):
                os.environ[n] = v
        config.load()  # the settings file, then the Keychain, as the builder'"'"'s Proxenos reads them
if not all(os.environ.get(n) for n in names):
    sys.exit(3)
client = {"installed": {"client_id": os.environ[names[0]], "client_secret": os.environ[names[1]]}}
out = Path(sys.argv[1])
out.write_text(json.dumps(client), encoding="utf-8")
out.chmod(0o600)
' "$stage/client/google.json" "$repo"; then
  say "Google sign-in is in the app"
else
  rm -f "$stage/client/google.json"
  say "no Google client in this build's environment or this Mac's Proxenos: the app is built without Google sign-in"
fi

say "building the page"
(cd "$cache/src/web" && npm ci --no-audit --no-fund && PROXENOS_STANDALONE=1 npm run build)
rm -rf "$stage/web"
cp -R "$cache/src/web/.next/standalone" "$stage/web"
cp -R "$cache/src/web/.next/static" "$stage/web/.next/static"
cp -R "$cache/src/web/public" "$stage/web/public"
cp "$cache/src/web/public/icon-512.png" "$stage/icon.png"

say "packing the app"
rm -rf "$desktop/dist"
(cd "$desktop" && npm ci --no-audit --no-fund &&
  npx --no-install electron-builder --config electron-builder.config.js "${platform[@]}" --publish never)
say "done:"
ls -1 "$desktop"/dist/*.dmg "$desktop"/dist/*.zip "$desktop"/dist/*.exe 2>/dev/null || true
