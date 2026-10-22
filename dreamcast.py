"""Dreamcast mode: live ffmpeg transcodes that a Sega Dreamcast can play.

LemonPlay (the Dreamcast DLNA client) decodes MPEG-1 video on the SH-4 and
hands audio straight to the AICA sound chip, which plays Yamaha ADPCM and
16-bit PCM in hardware. Every video and audio item gets an extra resource,
/dreamcast/<path>, that ffmpeg transcodes on the fly into an AVI holding:

- MPEG-1 video with no B-frames, sized to fit the profile's box in whole
  16-pixel macroblocks, at no more than 30 frames per second
- 44.1 kHz stereo 16-bit PCM (a=adpcm gives Yamaha ADPCM, a quarter of
  the size, but the AICA can't resume it mid-stream after a pause)

The client seeks by asking for the stream again with ?t=<seconds>; d=<seconds>
limits the length (LemonPlay's decode benchmark uses short clips) and
fill=<aspect> crops wider pictures to that shape (LemonPlay's zoom mode).
"""

import json
import os
import re
import subprocess
import threading

DREAMCAST_PATH_PREFIX = "/dreamcast/"
DREAMCAST_MIME_TYPE = "video/x-msvideo"

# The SH-4 decodes MPEG-1 at a roughly fixed cost per 16x16 macroblock that
# rises with bitrate (about 26 + 78 * bits_per_pixel microseconds, plus ~25%
# for networking and drawing during playback). The picture is made as large
# as fits the Dreamcast's 640x480 output and mb_per_sec. Measured on a real
# console with LemonPlay's playback benchmark: playback stays smooth while the
# decoder is under ~80% busy and starts skipping at ~85%. These defaults sit
# at ~75%: 448x256 for 24 fps widescreen, 384x288 for 4:3.
# Clients may ask for something else with the query parameters below.
DEFAULT_PROFILE = {
    "width": 640,
    "height": 480,
    "mb_per_sec": 11000,
    "bits_per_pixel": 0.35,
    "max_fps": 30.0,
    "audio": "pcm",
}

LIMITS = {
    "width": (64, 640),
    "height": (48, 480),
    "mb_per_sec": (500, 40000),
    "bits_per_pixel": (0.05, 4.0),
    "max_fps": (1.0, 30.0),
}

QUERY_KEYS = {
    "w": "width",
    "h": "height",
    "mbs": "mb_per_sec",
    "bpp": "bits_per_pixel",
    "fps": "max_fps",
}

AUDIO_CODECS = {"adpcm": "adpcm_yamaha", "pcm": "pcm_s16le"}

# Frame rates MPEG-1 can signal, highest first.
MPEG1_RATES = (
    (30.0, "30"),
    (30000 / 1001, "30000/1001"),
    (25.0, "25"),
    (24.0, "24"),
    (24000 / 1001, "24000/1001"),
)

_probe_cache = {}
_probe_lock = threading.Lock()

# One transcode per client address: a seek opens a new stream, and the old
# ffmpeg should not keep running until its socket times out.
_active = {}
_active_lock = threading.Lock()


def ffmpeg_available():
    """True when ffmpeg and ffprobe are on the PATH."""
    for tool in ("ffmpeg", "ffprobe"):
        try:
            subprocess.run(
                [tool, "-version"], capture_output=True, timeout=10, check=True
            )
        except (OSError, subprocess.SubprocessError):
            return False
    return True


def _ratio(text, default):
    """Parse ffprobe's "a/b" or "a:b" ratios."""
    parts = re.split(r"[/:]", str(text or ""))
    try:
        num, den = float(parts[0]), float(parts[1])
    except (IndexError, ValueError):
        return default
    if num <= 0 or den <= 0:
        return default
    return num / den


def probe(file_path):
    """Return the first real video stream's size, pixel aspect and frame rate.

    Returns None for audio files (cover art does not count as video).
    """
    try:
        stat = os.stat(file_path)
    except OSError:
        return None
    key = (file_path, stat.st_size, stat.st_mtime)
    with _probe_lock:
        if key in _probe_cache:
            return _probe_cache[key]

    info = None
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v",
                "-show_entries",
                "stream=width,height,sample_aspect_ratio,avg_frame_rate,r_frame_rate"
                ":stream_disposition=attached_pic",
                "-of",
                "json",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        for stream in json.loads(result.stdout or "{}").get("streams", []):
            if stream.get("disposition", {}).get("attached_pic"):
                continue
            info = {
                "width": int(stream["width"]),
                "height": int(stream["height"]),
                "sar": _ratio(stream.get("sample_aspect_ratio"), 1.0),
                "fps": _ratio(stream.get("avg_frame_rate"), 0.0)
                or _ratio(stream.get("r_frame_rate"), 0.0),
            }
            break
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        info = None

    with _probe_lock:
        _probe_cache[key] = info
    return info


def parse_profile(query):
    """Merge a request's query parameters (from parse_qs) into the profile."""
    profile = dict(DEFAULT_PROFILE)
    for short, name in QUERY_KEYS.items():
        if short in query:
            try:
                low, high = LIMITS[name]
                profile[name] = min(max(float(query[short][0]), low), high)
            except ValueError:
                pass
    audio = query.get("a", [""])[0]
    if audio in AUDIO_CODECS:
        profile["audio"] = audio
    try:
        profile["start"] = max(0.0, float(query.get("t", ["0"])[0]))
    except ValueError:
        profile["start"] = 0.0
    try:
        profile["length"] = max(0.0, float(query.get("d", ["0"])[0]))
    except ValueError:
        profile["length"] = 0.0
    try:
        profile["fill"] = min(max(float(query.get("fill", ["0"])[0]), 0.0), 4.0)
    except ValueError:
        profile["fill"] = 0.0
    return profile


def crop_to_fill(info, fill):
    """Crop the sides of a picture wider than the fill aspect (e.g. 16:9 to
    4:3 for LemonPlay's zoom mode). Returns (source info after cropping,
    ffmpeg crop filter or "")."""
    if not fill or info["width"] * info["sar"] / info["height"] <= fill + 0.01:
        return info, ""
    width = int(info["height"] * fill / info["sar"]) // 2 * 2
    cropped = dict(info, width=width)
    return cropped, f"crop={width}:{info['height']},"


def output_rate(source_fps, max_fps):
    """Pick an MPEG-1 frame rate: the source's, halved until it fits.

    Returns (ffmpeg rate text, frames per second).
    """
    fps = source_fps if source_fps > 0 else 24000 / 1001
    while fps > max_fps + 0.01:
        fps /= 2
    allowed = [(rate, text) for rate, text in MPEG1_RATES if rate <= max_fps + 0.01]
    if not allowed:
        rate, text = MPEG1_RATES[-1]
        return text, rate
    rate, text = min(allowed, key=lambda option: abs(option[0] - fps))
    return text, rate


def output_size(info, profile, fps):
    """Fit the source's display shape inside the profile in whole macroblocks.

    The picture keeps its display aspect ratio and grows until it hits the
    width/height box or the decode budget (macroblocks per second), then is
    trimmed to a multiple of 16 each way, cropping at most 15 pixels (the
    Dreamcast's YUV converter works in 16x16 macroblocks). Returns
    (scaled_w, scaled_h, out_w, out_h).
    """
    aspect = info["width"] * info["sar"] / info["height"]
    width = min(profile["width"], info["width"] * info["sar"])
    if width / aspect > profile["height"]:
        width = profile["height"] * aspect
    budget = profile["mb_per_sec"] / max(fps, 1.0)
    # Macroblocks grow with width squared: solve (w/16) * (w/aspect/16) = budget.
    width = min(width, 16 * (budget * aspect) ** 0.5)
    scaled_w = max(16, int(round(width / 2)) * 2)
    scaled_h = max(16, int(round(width / aspect / 2)) * 2)
    out_w = max(16, scaled_w // 16 * 16)
    out_h = max(16, scaled_h // 16 * 16)
    return scaled_w, scaled_h, out_w, out_h


def build_command(file_path, profile, info):
    """ffmpeg arguments that write the Dreamcast stream to stdout."""
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error"]
    if profile["start"] > 0:
        command += ["-ss", f"{profile['start']:.3f}"]
    command += ["-i", file_path]
    if profile["length"] > 0:
        command += ["-t", f"{profile['length']:.3f}"]

    if info:
        rate, fps = output_rate(info["fps"], profile["max_fps"])
        info, crop = crop_to_fill(info, profile.get("fill", 0))
        scaled_w, scaled_h, out_w, out_h = output_size(info, profile, fps)
        kbps = max(100, int(out_w * out_h * fps * profile["bits_per_pixel"] / 1000))
        command += [
            "-map",
            "0:V:0",
            "-map",
            "0:a:0?",
            "-vf",
            f"{crop}scale={scaled_w}:{scaled_h}:flags=lanczos,"
            f"crop={out_w}:{out_h},setsar=1,format=yuv420p",
            "-r",
            rate,
            "-c:v",
            "mpeg1video",
            "-b:v",
            f"{kbps}k",
            "-maxrate",
            f"{kbps * 2}k",
            "-bufsize",
            f"{kbps * 2}k",
            # No B-frames: they cost the decoder a second reference frame and
            # bidirectional prediction for little gain at LAN bitrates.
            "-bf",
            "0",
            "-g",
            "60",
            "-mbd",
            "rd",
            "-trellis",
            "1",
            "-cmp",
            "rd",
            "-subcmp",
            "rd",
        ]
    else:
        command += ["-map", "0:a:0", "-vn"]

    command += [
        "-c:a",
        AUDIO_CODECS[profile["audio"]],
        "-ar",
        "44100",
        "-ac",
        "2",
        "-sn",
        "-dn",
        "-f",
        "avi",
        "pipe:1",
    ]
    return command


def stream(handler, file_path, query, head_only=False):
    """Send a live Dreamcast transcode of file_path to the handler's client."""
    profile = parse_profile(query)
    info = probe(file_path)
    command = build_command(file_path, profile, info)

    handler.send_response(200)
    handler.send_header("Content-Type", DREAMCAST_MIME_TYPE)
    handler.send_header(
        "ContentFeatures.DLNA.ORG",
        "DLNA.ORG_OP=10;DLNA.ORG_CI=1;DLNA.ORG_FLAGS=01700000000000000000000000000000",
    )
    handler.send_header("TransferMode.DLNA.ORG", "Streaming")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.close_connection = True
    if head_only:
        return

    if handler.verbose:
        print(f"Dreamcast transcode: {' '.join(command)}")
    client = handler.client_address[0]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
    )
    with _active_lock:
        previous = _active.get(client)
        _active[client] = process
    if previous and previous.poll() is None:
        previous.kill()

    errors = []
    error_reader = threading.Thread(
        target=lambda: errors.append(process.stderr.read()), daemon=True
    )
    error_reader.start()
    sent = 0
    try:
        while True:
            chunk = process.stdout.read(64 * 1024)
            if not chunk:
                break
            handler.wfile.write(chunk)
            sent += len(chunk)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        error_reader.join(timeout=2)
        with _active_lock:
            if _active.get(client) is process:
                del _active[client]
    message = b"".join(errors).decode("utf-8", "replace").strip()
    if message and process.returncode not in (0, -9):
        print(f"Dreamcast transcode error for {os.path.basename(file_path)}: {message}")
    if handler.verbose:
        print(f"Dreamcast transcode ended after {sent:,} bytes")


def resource_didl(media_url, duration, escape):
    """The extra <res> element that points LemonPlay at the transcode."""
    url = media_url.replace("/media/", DREAMCAST_PATH_PREFIX, 1)
    protocol = (
        f"http-get:*:{DREAMCAST_MIME_TYPE}:"
        "DLNA.ORG_OP=10;DLNA.ORG_CI=1;DLNA.ORG_FLAGS=01700000000000000000000000000000"
    )
    return f'    <res protocolInfo="{protocol}" duration="{duration}">{escape(url)}</res>\n'
