"""Pre-packaging smoke test, run in CI before building the app.

Deliberately does NOT download from YouTube: GitHub's servers are often
blocked by YouTube, which would fail the build even when the app works fine
on a home machine. Instead this builds a small test clip locally and runs it
through the real pitch-shifting code, which is the part that packaging and
dependency changes actually break.

Tests the source, not the frozen bundle.
"""
import os
import re
import subprocess
import sys
import tempfile

import desktop

FAILURES = []


def check(name, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not condition:
        FAILURES.append(name)


def probe(path):
    out = subprocess.run([desktop.FFMPEG, "-i", path], capture_output=True, text=True).stderr
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    seconds = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3)) if dur else None
    streams = dict(re.findall(r"Stream #\S+: (Video|Audio): (\w+)", out))
    return seconds, streams


def main():
    import yt_dlp
    print("yt-dlp", yt_dlp.version.__version__, "| python", sys.version.split()[0])

    check("ffmpeg binary exists", os.path.isfile(desktop.FFMPEG), desktop.FFMPEG)

    # The filters that do the pitch shift must be present in this ffmpeg build.
    filters = subprocess.run([desktop.FFMPEG, "-filters"], capture_output=True, text=True).stdout
    for f in ("asetrate", "aresample", "atempo"):
        check(f"ffmpeg has '{f}' filter", f" {f} " in filters or f"{f} " in filters)

    tmp = tempfile.mkdtemp()
    src = os.path.join(tmp, "input.mp4")
    out = os.path.join(tmp, "output.mp4")

    # 3-second clip: moving video + 440Hz tone, same codecs YouTube gives us.
    subprocess.run([
        desktop.FFMPEG, "-y",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
        "-shortest", src,
    ], check=True, capture_output=True)
    check("test clip created", os.path.exists(src) and os.path.getsize(src) > 0)

    # The real pitch-shift path used by the app.
    desktop.Api()._pitch_shift(src, out, -1)
    check("pitch shift produced a file", os.path.exists(out) and os.path.getsize(out) > 0)

    in_dur, in_streams = probe(src)
    out_dur, out_streams = probe(out)
    check("video stream preserved", out_streams.get("Video") == in_streams.get("Video"),
          f"{in_streams.get('Video')} -> {out_streams.get('Video')}")
    check("audio stream present", "Audio" in out_streams, str(out_streams.get("Audio")))
    check("duration unchanged (tempo preserved)",
          in_dur and out_dur and abs(in_dur - out_dur) < 0.35, f"{in_dur}s -> {out_dur}s")

    # Sample-rate detection must find a real rate, not silently fall back.
    check("sample rate detected", desktop.Api()._get_sample_rate(src) in (44100, 48000),
          str(desktop.Api()._get_sample_rate(src)))

    # Friendly error text still explains a YouTube block.
    msg = desktop.download_error_message(Exception("ERROR: unable to download video data: HTTP Error 403: Forbidden"))
    check("403 produces 'needs an update' message", "needs an update" in msg and "403" in msg)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        sys.exit(1)
    print("All smoke checks passed.")


if __name__ == "__main__":
    main()
