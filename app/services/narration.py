
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from app.services.renderer import OUTPUT_DIR


def generate_narration(script: str, voice: str = "Aman") -> str:
    """Generate local speech on macOS or Linux and convert it to WAV."""
    if not script or not script.strip():
        raise ValueError("Script cannot be empty")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    job_suffix = uuid.uuid4().hex
    wav_path = OUTPUT_DIR / f"narration_{job_suffix}.wav"

    engine = os.getenv("TTS_ENGINE", "auto").lower()
    if engine not in {"auto", "macos", "espeak"}:
        raise ValueError("TTS_ENGINE must be auto, macos, or espeak")

    use_macos = engine == "macos" or (
        engine == "auto" and sys.platform == "darwin"
    )

    if use_macos:
        if not shutil.which("say"):
            raise RuntimeError("macOS 'say' command is unavailable")

        aiff_path = OUTPUT_DIR / f"narration_{job_suffix}.aiff"
        try:
            subprocess.run(
                ["say", "-v", voice, "-o", str(aiff_path), script],
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
            )
            subprocess.run(
                [
                    os.getenv("FFMPEG_BINARY", "ffmpeg"),
                    "-y", "-i", str(aiff_path),
                    "-ac", "2", "-ar", "44100",
                    "-c:a", "pcm_s16le", str(wav_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        finally:
            aiff_path.unlink(missing_ok=True)

    else:
        espeak = shutil.which("espeak-ng")
        if not espeak:
            raise RuntimeError(
                "Linux narration requires espeak-ng. Install it in the container."
            )

        language = os.getenv("ESPEAK_VOICE", "en-in")
        subprocess.run(
            [
                espeak, "-v", language,
                "-w", str(wav_path), script,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )

        subprocess.run(
            [
                os.getenv("FFMPEG_BINARY", "ffmpeg"),
                "-y", "-i", str(wav_path),
                "-ac", "2", "-ar", "44100",
                "-c:a", "pcm_s16le",
                str(wav_path.with_suffix(".normalized.wav")),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        normalized = wav_path.with_suffix(".normalized.wav")
        normalized.replace(wav_path)

    return str(wav_path)


def format_srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def write_srt(scenes: list[dict], output_path: str) -> str:
    """Write sentence-level captions using scene timings."""
    lines = []

    for index, scene in enumerate(scenes, start=1):
        start = float(scene["start_s"])
        end = float(scene["end_s"])
        text = scene["text"].strip()

        if end <= start or not text:
            continue

        lines.extend([
            str(index),
            f"{format_srt_time(start)} --> {format_srt_time(end)}",
            text,
            "",
        ])

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)
