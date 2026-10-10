#!/bin/bash
set -e

cd "$(dirname "$0")"

# Create venv if needed
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    python3.12 -m venv .venv
fi

echo "Installing dependencies..."
# -U always pulls the newest yt-dlp: YouTube changes often and old versions break.
.venv/bin/pip install -q -U pywebview imageio-ffmpeg "yt-dlp>=2026.8.19" pyinstaller
echo "Bundling yt-dlp $(.venv/bin/python -c 'import yt_dlp; print(yt_dlp.version.__version__)')"

echo "Building app..."
.venv/bin/pyinstaller karaoke-pitcher.spec --noconfirm

# Create distributable zip
APP_NAME="Karaoke Pitch Shifter"
if [ -d "dist/${APP_NAME}.app" ]; then
    echo "Creating zip for distribution..."
    cd dist
    rm -f "${APP_NAME}.zip"
    ditto -c -k --keepParent "${APP_NAME}.app" "${APP_NAME}.zip"
    cd ..
    echo ""
    echo "Done! Distributable files:"
    echo "  App:  dist/${APP_NAME}.app"
    echo "  Zip:  dist/${APP_NAME}.zip ($(du -sh "dist/${APP_NAME}.zip" | cut -f1) — share this)"
elif [ -d "dist/${APP_NAME}" ]; then
    echo ""
    echo "Done! Distributable folder: dist/${APP_NAME}/"
fi
