import os
import re
import shutil
import subprocess
import tempfile

import streamlit as st
import yt_dlp

st.set_page_config(page_title="Karaoke Pitch Shifter", page_icon="🎤")
st.title("Karaoke Pitch Shifter")
st.write("Paste a YouTube karaoke link, choose how many semitones to shift, and download the result.")

url = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=...")
semitones = st.slider(
    "Semitones",
    min_value=-6,
    max_value=6,
    value=0,
    step=1,
    help="Negative = lower key, Positive = higher key",
)


def is_valid_youtube_url(url: str) -> bool:
    pattern = r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)"
    return bool(re.search(pattern, url))


FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def check_ffmpeg() -> tuple[bool, str]:
    """Check that ffmpeg is installed."""
    try:
        subprocess.run(
            [FFMPEG, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return True, ""
    except FileNotFoundError:
        return False, (
            "FFmpeg is not installed. Install it with: `brew install ffmpeg` "
            "(on macOS) or `sudo apt install ffmpeg` (on Linux)."
        )


def download_video(url: str, output_path: str) -> str:
    """Download video and return its title.

    YouTube now usually serves video and audio separately, so fetch both and
    let yt-dlp merge them into an MP4 with ffmpeg.
    """
    base, _ = os.path.splitext(output_path)
    ydl_opts = {
        "format": "bv*[ext=mp4][vcodec^=avc1][height<=720]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "ffmpeg_location": FFMPEG,
        "outtmpl": base + ".%(ext)s",
        "noplaylist": True,
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    return info.get("title", "karaoke")


def get_sample_rate(filepath: str) -> int:
    """Get the audio sample rate of a file using ffprobe."""
    cmd = [
        FFMPEG.replace("ffmpeg", "ffprobe"),
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate",
        "-of", "csv=p=0",
        filepath,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return int(result.stdout.strip()) if result.stdout.strip() else 44100


def pitch_shift(input_path: str, output_path: str, semitones: int) -> None:
    """Pitch-shift audio using asetrate + aresample + atempo, copying video as-is.

    asetrate changes the sample rate to shift pitch, aresample restores the
    original rate, and atempo corrects the speed change so tempo is preserved.
    """
    rate = get_sample_rate(input_path)
    factor = 2 ** (semitones / 12)
    new_rate = int(rate * factor)
    tempo = 1 / factor
    af = f"asetrate={new_rate},aresample={rate},atempo={tempo}"
    cmd = [
        FFMPEG,
        "-y",
        "-i",
        input_path,
        "-af",
        af,
        "-c:v",
        "copy",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-500:])


if st.button("Pitch Shift!"):
    if not url or not url.strip():
        st.error("Please paste a YouTube URL above.")
    elif not is_valid_youtube_url(url):
        st.error("That doesn't look like a YouTube link. Please paste a full YouTube URL.")
    elif semitones == 0:
        st.warning("Semitones is set to 0 — that means no pitch change. Adjust the slider or download the original from YouTube.")
    else:
        # Check ffmpeg before doing anything
        ok, err_msg = check_ffmpeg()
        if not ok:
            st.error(err_msg)
        else:
            tmpdir = tempfile.mkdtemp()
            try:
                input_path = os.path.join(tmpdir, "input.mp4")
                output_path = os.path.join(tmpdir, "output.mp4")

                with st.spinner("Downloading video..."):
                    try:
                        title = download_video(url, input_path)
                    except Exception as e:
                        st.error(
                            "Couldn't download that video. "
                            "It might be private, age-restricted, or the link might be wrong."
                        )
                        st.caption(f"Details: {str(e)[:200]}")
                        st.stop()

                with st.spinner("Shifting pitch..."):
                    try:
                        pitch_shift(input_path, output_path, semitones)
                    except Exception:
                        st.error("Something went wrong during pitch shifting. Try a different video or a smaller pitch change.")
                        st.stop()

                safe_title = re.sub(r"[^\w\s-]", "", title)[:50].strip()
                filename = f"{safe_title} ({semitones:+d} semitones).mp4"

                with open(output_path, "rb") as f:
                    video_bytes = f.read()

                st.success("Done! Click below to download.")
                st.download_button(
                    label="Download pitched video",
                    data=video_bytes,
                    file_name=filename,
                    mime="video/mp4",
                )
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
