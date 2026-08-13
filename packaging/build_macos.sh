#!/usr/bin/env bash
# Builds the macOS .app (via packaging/telescope_simulator.spec) and wraps
# it into a distributable .dmg using hdiutil (built into macOS, no extra
# dependency). Must be run ON a Mac -- PyInstaller does not cross-compile.
# See README's "Packaging standalone builds" -> "macOS (.dmg)" section.
set -euo pipefail
cd "$(dirname "$0")/.."

APP_NAME="TelescopeSimulator"
VERSION=$(python3 -c "from telescope_simulator.version import APP_VERSION; print(APP_VERSION)")
DMG_PATH="dist/${APP_NAME}-${VERSION}-arm64.dmg"

pip install -r requirements.txt -r requirements-build.txt
pyinstaller packaging/telescope_simulator.spec --noconfirm

STAGE_DIR="dist/dmg_stage"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
cp -R "dist/${APP_NAME}.app" "$STAGE_DIR/"
ln -s /Applications "$STAGE_DIR/Applications"

rm -f "$DMG_PATH"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE_DIR" -ov -format UDZO "$DMG_PATH"
rm -rf "$STAGE_DIR"

echo "Built $DMG_PATH"
