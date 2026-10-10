# -*- mode: python ; coding: utf-8 -*-
# Cross-platform build spec.
#   macOS   -> "Karaoke Pitch Shifter.app" (folder bundle)
#   Windows -> "Karaoke Pitch Shifter.exe" (ONE file, so there is nothing to
#              install and no way to double-click the wrong thing)
import os
import sys

import imageio_ffmpeg

ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

APP_NAME = "Karaoke Pitch Shifter"

hidden = [
    "imageio_ffmpeg",
    "yt_dlp",
    "webview",
]
if IS_WIN:
    # pywebview drives the Edge WebView2 control through pythonnet on Windows.
    hidden += ["webview.platforms.winforms", "clr", "pythonnet"]
elif IS_MAC:
    hidden += ["webview.platforms.cocoa"]

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=[(ffmpeg_exe, "imageio_ffmpeg/binaries")],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "streamlit"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if IS_WIN:
    # Single-file build: binaries + datas go inside the EXE, no COLLECT step.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        target_arch=None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        strip=False,
        upx=False,
        console=False,
        target_arch=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name=APP_NAME,
    )
    if IS_MAC:
        app = BUNDLE(
            coll,
            name=APP_NAME + ".app",
            bundle_identifier="com.karaoke.pitchshifter",
            info_plist={
                "CFBundleShortVersionString": "1.1.0",
                "NSHighResolutionCapable": True,
            },
        )
