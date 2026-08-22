#!/bin/bash
set -e

APP_NAME="Time-to-Sleep"
DMG_NAME="$APP_NAME.dmg"
STAGING_DIR="dmg_staging"

# Rebuild app
./build.sh

# Prepare staging folder
rm -rf "$STAGING_DIR" "$DMG_NAME"
mkdir -p "$STAGING_DIR"
cp -R "$APP_NAME.app" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"

# Create DMG
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING_DIR" -ov -format UDZO "$DMG_NAME"

# Clean up
rm -rf "$STAGING_DIR"

echo "✅ Created macOS DMG at macOS/$DMG_NAME"
