import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

import webview
import yt_dlp

# ---------------------------------------------------------------------------
# Locate bundled ffmpeg (via imageio-ffmpeg) or fall back to system ffmpeg
# ---------------------------------------------------------------------------

def _find_ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        path = shutil.which("ffmpeg")
        if path:
            return path
        # Common Homebrew locations
        for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
            if os.path.isfile(p):
                return p
        return "ffmpeg"


FFMPEG = _find_ffmpeg()

# YouTube now usually serves video and audio as separate streams, so download
# both (H.264 video up to 720p + AAC audio) and let yt-dlp merge them with
# ffmpeg. Falls back to a single combined file, then to anything available.
YTDL_FORMAT = "bv*[ext=mp4][vcodec^=avc1][height<=720]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"


def download_video(url: str, output_path: str) -> str:
    """Download a YouTube video to output_path (.mp4) and return its title."""
    base, _ = os.path.splitext(output_path)
    ydl_opts = {
        "format": YTDL_FORMAT,
        "merge_output_format": "mp4",
        "ffmpeg_location": FFMPEG,
        "outtmpl": base + ".%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    if not os.path.exists(output_path):
        raise RuntimeError("Download finished but no MP4 file was produced")
    return info.get("title", "karaoke")


def download_error_message(e: Exception) -> str:
    """Friendly message plus the short technical reason, for easier debugging."""
    reason = re.sub(r"^ERROR:\s*(\[\w+\]\s*[\w-]+:\s*)?", "", str(e)).split("\n")[0][:160]
    msg = "Couldn't download that video. It might be private, age-restricted, or the link might be wrong."
    if re.search(r"403|Forbidden|not a bot|Sign in|format is not available", str(e), re.I):
        msg = ("Couldn't download that video. YouTube may have changed something, "
               "so this app probably needs an update.")
    return f"{msg}\n\nDetails: {reason}"

# ---------------------------------------------------------------------------
# Backend logic (called from JS via pywebview API)
# ---------------------------------------------------------------------------

class Api:
    def __init__(self):
        self._window = None
        self._cancel = False

    def set_window(self, window):
        self._window = window

    def cancel(self):
        self._cancel = True

    def process(self, url: str, semitones: int):
        """Download and pitch-shift a YouTube video. Runs in a thread."""
        self._cancel = False
        thread = threading.Thread(target=self._process, args=(url, semitones), daemon=True)
        thread.start()

    def _emit(self, event: str, data: dict):
        payload = json.dumps(data)
        self._window.evaluate_js(f"onBackendEvent({json.dumps(event)}, {payload})")

    def _process(self, url: str, semitones: int):
        tmpdir = tempfile.mkdtemp()
        try:
            # Validate URL
            pattern = r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)"
            if not re.search(pattern, url):
                self._emit("error", {"message": "That doesn't look like a YouTube link."})
                return

            if semitones == 0:
                self._emit("error", {"message": "Semitones is 0 — no pitch change needed."})
                return

            # Download
            self._emit("status", {"message": "Downloading video..."})
            input_path = os.path.join(tmpdir, "input.mp4")
            try:
                title = self._download(url, input_path)
            except Exception as e:
                self._emit("error", {"message": download_error_message(e)})
                return

            if self._cancel:
                return

            # Pitch shift
            self._emit("status", {"message": "Shifting pitch..."})
            output_path = os.path.join(tmpdir, "output.mp4")
            try:
                self._pitch_shift(input_path, output_path, semitones)
            except Exception as e:
                self._emit("error", {
                    "message": "Something went wrong during pitch shifting. Try a different video or a smaller shift."
                })
                return

            if self._cancel:
                return

            # Prompt user to save
            safe_title = re.sub(r"[^\w\s-]", "", title)[:50].strip()
            default_name = f"{safe_title} ({semitones:+d} semitones).mp4"

            self._emit("status", {"message": "Choose where to save..."})
            save_path = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=default_name,
                file_types=("MP4 Video (*.mp4)",),
            )

            if save_path:
                dest = save_path if isinstance(save_path, str) else save_path[0]
                if not dest.endswith(".mp4"):
                    dest += ".mp4"
                shutil.copy2(output_path, dest)
                self._emit("done", {"message": f"Saved!", "path": dest})
            else:
                self._emit("error", {"message": "Save cancelled."})

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _download(self, url: str, output_path: str) -> str:
        return download_video(url, output_path)

    def _get_sample_rate(self, filepath: str) -> int:
        cmd = [
            FFMPEG,
            "-i", filepath,
            "-hide_banner",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        # Parse sample rate from ffmpeg output (e.g., "44100 Hz")
        match = re.search(r"(\d{4,6})\s*Hz", result.stderr)
        return int(match.group(1)) if match else 44100

    def _pitch_shift(self, input_path: str, output_path: str, semitones: int):
        rate = self._get_sample_rate(input_path)
        factor = 2 ** (semitones / 12)
        new_rate = int(rate * factor)
        tempo = 1 / factor
        af = f"asetrate={new_rate},aresample={rate},atempo={tempo}"
        cmd = [
            FFMPEG, "-y",
            "-i", input_path,
            "-af", af,
            "-c:v", "copy",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-500:])


# ---------------------------------------------------------------------------
# HTML / CSS / JS — the entire UI in one string
# ---------------------------------------------------------------------------

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Karaoke Pitch Shifter</title>
<style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background: #1a1a2e;
        color: #eee;
        display: flex;
        justify-content: center;
        align-items: center;
        min-height: 100vh;
        padding: 20px;
    }
    .card {
        background: #16213e;
        border-radius: 16px;
        padding: 40px;
        width: 100%;
        max-width: 480px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.3);
    }
    h1 {
        font-size: 24px;
        margin-bottom: 6px;
        text-align: center;
    }
    .subtitle {
        text-align: center;
        color: #8892b0;
        font-size: 14px;
        margin-bottom: 28px;
    }
    label {
        display: block;
        font-size: 13px;
        font-weight: 600;
        color: #8892b0;
        margin-bottom: 6px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    input[type="text"] {
        width: 100%;
        padding: 12px 14px;
        border: 2px solid #2a3a5c;
        border-radius: 8px;
        background: #0f1a30;
        color: #eee;
        font-size: 15px;
        outline: none;
        transition: border-color 0.2s;
    }
    input[type="text"]:focus { border-color: #6c63ff; }
    input[type="text"]::placeholder { color: #4a5568; }
    .field { margin-bottom: 22px; }
    .slider-row {
        display: flex;
        align-items: center;
        gap: 14px;
    }
    input[type="range"] {
        flex: 1;
        accent-color: #6c63ff;
        height: 6px;
    }
    .semitone-value {
        font-size: 22px;
        font-weight: 700;
        min-width: 50px;
        text-align: center;
        color: #6c63ff;
    }
    .slider-labels {
        display: flex;
        justify-content: space-between;
        font-size: 11px;
        color: #4a5568;
        margin-top: 4px;
    }
    button {
        width: 100%;
        padding: 14px;
        border: none;
        border-radius: 8px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s, transform 0.1s;
    }
    button:active { transform: scale(0.98); }
    .btn-primary {
        background: #6c63ff;
        color: white;
    }
    .btn-primary:hover { background: #5a52d5; }
    .btn-primary:disabled {
        background: #3a3a5c;
        color: #6a6a8a;
        cursor: not-allowed;
        transform: none;
    }
    .status {
        margin-top: 20px;
        padding: 14px;
        border-radius: 8px;
        font-size: 14px;
        text-align: center;
        display: none;
        white-space: pre-line;
        overflow-wrap: anywhere;
    }
    .status.info { display: block; background: #1a2744; color: #8892b0; }
    .status.error { display: block; background: #2d1b1b; color: #ff6b6b; }
    .status.success { display: block; background: #1b2d1b; color: #51cf66; }
    .spinner {
        display: inline-block;
        width: 16px;
        height: 16px;
        border: 2px solid #8892b0;
        border-top-color: transparent;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        vertical-align: middle;
        margin-right: 8px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="card">
    <h1>Karaoke Pitch Shifter</h1>
    <p class="subtitle">Paste a YouTube link, adjust the key, and save.</p>

    <div class="field">
        <label for="url">YouTube URL</label>
        <input type="text" id="url" placeholder="https://www.youtube.com/watch?v=..." />
    </div>

    <div class="field">
        <label>Semitones</label>
        <div class="slider-row">
            <input type="range" id="semitones" min="-6" max="6" value="-1" step="1" />
            <span class="semitone-value" id="semitoneDisplay">-1</span>
        </div>
        <div class="slider-labels">
            <span>Lower key</span>
            <span>Higher key</span>
        </div>
    </div>

    <button class="btn-primary" id="goBtn" onclick="go()">Pitch Shift!</button>

    <div class="status" id="status"></div>
</div>

<script>
    const slider = document.getElementById('semitones');
    const display = document.getElementById('semitoneDisplay');
    const statusEl = document.getElementById('status');
    const goBtn = document.getElementById('goBtn');

    slider.addEventListener('input', () => {
        const v = parseInt(slider.value);
        display.textContent = (v > 0 ? '+' : '') + v;
    });

    function go() {
        const url = document.getElementById('url').value.trim();
        const semitones = parseInt(slider.value);
        if (!url) {
            showStatus('error', 'Please paste a YouTube URL above.');
            return;
        }
        goBtn.disabled = true;
        goBtn.textContent = 'Processing...';
        showStatus('info', '<span class="spinner"></span> Starting...');
        pywebview.api.process(url, semitones);
    }

    function onBackendEvent(event, data) {
        if (event === 'status') {
            showStatus('info', '<span class="spinner"></span> ' + data.message);
        } else if (event === 'error') {
            showStatus('error', '');
            statusEl.textContent = data.message;
            resetButton();
        } else if (event === 'done') {
            showStatus('success', data.message);
            resetButton();
        }
    }

    function showStatus(type, html) {
        statusEl.className = 'status ' + type;
        statusEl.innerHTML = html;
    }

    function resetButton() {
        goBtn.disabled = false;
        goBtn.textContent = 'Pitch Shift!';
    }
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    api = Api()
    window = webview.create_window(
        "Karaoke Pitch Shifter",
        html=HTML,
        js_api=api,
        width=560,
        height=520,
        resizable=True,
        min_size=(400, 450),
    )
    api.set_window(window)
    webview.start()


if __name__ == "__main__":
    main()
