# Karaoke Pitch Shifter

Paste a YouTube karaoke link, pick how many semitones to shift, get back an
MP4 with the audio transposed and the video untouched. Tempo is preserved.

For the non-technical version, see [INSTRUCTIONS-FOR-PARENTS.md](INSTRUCTIONS-FOR-PARENTS.md).

## How it works

1. **yt-dlp** downloads the video. YouTube now serves video and audio as
   separate streams, so both are fetched and merged into an MP4.
2. **ffmpeg** shifts the pitch with `asetrate` + `aresample` + `atempo`:
   `asetrate` moves the pitch, `atempo` undoes the resulting speed change.
   The video stream is copied with `-c:v copy`, so it is never re-encoded
   and processing is fast.

ffmpeg ships inside the app via `imageio-ffmpeg` — users install nothing.

## Builds

Pushing to `main` builds both platforms in GitHub Actions
(`.github/workflows/build.yml`) and publishes them to the **`latest`**
release:

| Platform | Asset | Shape |
|---|---|---|
| Windows | `KaraokePitchShifter-Windows.exe` | one file, nothing to install |
| macOS (Apple Silicon) | `KaraokePitchShifter-macOS-AppleSilicon.zip` | `.app` bundle |

The permanent download link is `releases/latest/download/<asset name>`, so
the same link always serves the newest build.

### Why it rebuilds on a schedule

yt-dlp is frozen into each build, and YouTube breaks older versions every
few months. The workflow also runs on the 1st and 15th, always installing
the newest yt-dlp, so a working build is waiting before anyone notices a
broken one. `ci_smoketest.py` gates each build.

Intel Macs are not built. Add `macos-13` to the workflow matrix if needed.

Windows builds are unsigned, so SmartScreen warns on first run and some
antivirus engines false-positive on PyInstaller output.

## Local development

Requires Python 3.12+ and (for the Streamlit version only) system ffmpeg.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt pywebview imageio-ffmpeg
.venv/bin/python desktop.py          # native desktop window
.venv/bin/streamlit run app.py       # browser version, localhost:8501
.venv/bin/python ci_smoketest.py     # pipeline checks, no network needed
./build.sh                           # build the Mac .app locally
```

`ci_smoketest.py` deliberately avoids YouTube: GitHub's servers are often
blocked by it, which would fail builds that work fine on a home machine. It
tests the pitch-shift path against a locally generated clip instead, and it
tests the source rather than the packaged binary.
