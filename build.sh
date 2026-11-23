#!/usr/bin/env bash
set -e

echo "→ Installing dependencies..."
pip3 install -r requirements.txt pyinstaller pillow

echo "→ Generating icon..."
python3 make_icon.py

echo "→ Building NetWatch.app (arm64)..."
python3 -m PyInstaller \
  --windowed \
  --name "NetWatch" \
  --icon "assets/icon.icns" \
  --osx-bundle-identifier "com.cyrillical00.netwatch" \
  --target-arch arm64 \
  --add-data "assets:assets" \
  --hidden-import "requests" \
  --clean \
  app.py

echo ""
echo "✓ Build complete: dist/NetWatch.app"
echo "  Drag to /Applications to install."
echo ""

# Optional: create a zip for GitHub Releases
cd dist
zip -r NetWatch-macOS-arm64.zip NetWatch.app
echo "✓ Release archive: dist/NetWatch-macOS-arm64.zip"
shasum -a 256 NetWatch-macOS-arm64.zip
echo "  ^ put this SHA-256 in Formula/netwatch.rb before publishing the release"
