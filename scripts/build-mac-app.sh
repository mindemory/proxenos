#!/bin/bash
# Build Proxenos.app, the page in a window of its own (mac/Proxenos.swift), and put it in
# ~/Applications, so it opens from Launchpad, Spotlight or the Dock like any app. Needs the Swift
# compiler from Xcode's command line tools (xcode-select --install). The page itself must be
# running: scripts/install-app.sh keeps it up from login. Running this again replaces the app.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd -P)"
apps="$HOME/Applications"
app="$apps/Proxenos.app"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

command -v swiftc >/dev/null || {
  echo "build-mac-app: no Swift compiler; run xcode-select --install, then this again." >&2
  exit 1
}

mkdir -p "$work/Proxenos.app/Contents/MacOS" "$work/Proxenos.app/Contents/Resources"
swiftc -O -swift-version 5 -o "$work/Proxenos.app/Contents/MacOS/Proxenos" "$repo/mac/Proxenos.swift"

# The icon, from the page's own, at every size macOS asks for.
set_dir="$work/AppIcon.iconset"
mkdir -p "$set_dir"
for size in 16 32 128 256 512; do
  sips -z $size $size "$repo/web/public/icon-512.png" --out "$set_dir/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z $double $double "$repo/web/public/icon-512.png" --out "$set_dir/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$set_dir" -o "$work/Proxenos.app/Contents/Resources/AppIcon.icns"

cat >"$work/Proxenos.app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Proxenos</string>
  <key>CFBundleDisplayName</key><string>Proxenos</string>
  <key>CFBundleIdentifier</key><string>local.proxenos.app</string>
  <key>CFBundleExecutable</key><string>Proxenos</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST
codesign --force --sign - "$work/Proxenos.app" 2>/dev/null || true  # ad hoc, for this Mac only

mkdir -p "$apps"
rm -rf "$app"
mv "$work/Proxenos.app" "$app"
echo "Built $app. Open it from Launchpad or Spotlight, and keep it in the Dock."
