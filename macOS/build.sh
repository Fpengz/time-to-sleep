#!/bin/bash
set -e

APP_NAME="Time-to-Sleep"
BUNDLE_DIR="$APP_NAME.app"
CONTENTS_DIR="$BUNDLE_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

# Clean up previous build
rm -rf "$BUNDLE_DIR"

# Create directory structure
mkdir -p "$MACOS_DIR"
mkdir -p "$RESOURCES_DIR"

# Copy Info.plist and Icons
cp Info.plist "$CONTENTS_DIR/"
cp AppIcon.icns "$RESOURCES_DIR/"
cp MenuIcon.png "$RESOURCES_DIR/"

# Compile Swift files
swiftc -o "$MACOS_DIR/TimeToSleep" Sources/*.swift

echo "✅ App built successfully at macOS/$BUNDLE_DIR"
echo "You can run it with: open 'macOS/$BUNDLE_DIR'"
