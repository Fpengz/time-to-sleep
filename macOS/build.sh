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

# Copy Info.plist, PkgInfo and Icons
cp Info.plist "$CONTENTS_DIR/"
echo -n "APPL????" > "$CONTENTS_DIR/PkgInfo"
cp AppIcon.icns "$RESOURCES_DIR/"
cp MenuIcon.png "$RESOURCES_DIR/"

# Ensure Rust release binary exists and bundle it
if [ ! -f "../target/release/time-to-sleep" ]; then
    echo "⚙️ Building release Rust binary..."
    (cd .. && cargo build --release)
fi

cp "../target/release/time-to-sleep" "$RESOURCES_DIR/"
chmod +x "$RESOURCES_DIR/time-to-sleep"

# Compile Swift files (attempt Universal binary, fallback to host architecture)
echo "⚙️ Compiling Swift frontend..."
TMP_DIR=$(mktemp -d /tmp/tts_swift_build.XXXXXX)
if swiftc -target arm64-apple-macos13.0 -O -o "$TMP_DIR/TimeToSleep_arm64" Sources/*.swift 2>/dev/null && \
   swiftc -target x86_64-apple-macos13.0 -O -o "$TMP_DIR/TimeToSleep_x86_64" Sources/*.swift 2>/dev/null; then
    lipo -create "$TMP_DIR/TimeToSleep_arm64" "$TMP_DIR/TimeToSleep_x86_64" -output "$MACOS_DIR/TimeToSleep"
else
    swiftc -target "$(uname -m)-apple-macos13.0" -O -o "$MACOS_DIR/TimeToSleep" Sources/*.swift
fi
rm -rf "$TMP_DIR"
chmod +x "$MACOS_DIR/TimeToSleep"

# Code sign inner binary and app bundle
echo "🔒 Signing app bundle..."
codesign --force --sign - "$RESOURCES_DIR/time-to-sleep"
codesign --force --deep --sign - "$BUNDLE_DIR"

# Verify bundle signature
codesign --verify --deep --strict "$BUNDLE_DIR"

echo "✅ App built and signed successfully at macOS/$BUNDLE_DIR"
echo "You can run it with: open 'macOS/$BUNDLE_DIR'"
