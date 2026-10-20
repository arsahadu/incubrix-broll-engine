
import json
import math
import os
import subprocess
from pathlib import Path


OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DIMENSIONS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}

FPS = 30
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"

SUBTITLE_STYLE = (
    "FontName=Arial,"
    "FontSize=22,"
    "PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,"
    "BorderStyle=1,"
    "Outline=2,"
    "Shadow=1,"
    "Alignment=2"
)


def _ffmpeg_binary() -> str:
    return os.getenv("FFMPEG_BINARY", "ffmpeg")


def _ffprobe_binary() -> str:
    return os.getenv("FFPROBE_BINARY", "ffprobe")


def _run_command(
    command: list[str],
    timeout: int = 600,
) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Media processing timed out after {timeout} seconds."
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            "Could not start FFmpeg. Check your FFmpeg installation "
            "and FFMPEG_BINARY configuration."
        ) from exc

    if result.returncode != 0:
        raise RuntimeError(
            "Media processing failed:\n"
            f"{result.stderr[-3000:]}"
        )

    return result


def _probe_duration(path: Path) -> float:
    command = [
        _ffprobe_binary(),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        if result.returncode != 0:
            raise ValueError(result.stderr[-1000:])

        duration = float(result.stdout.strip())

        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Invalid media duration.")

        return duration

    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RuntimeError(
            f"Could not determine duration: {path.name}"
        ) from exc


def _probe_video(path: Path) -> dict:
    command = [
        _ffprobe_binary(),
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,pix_fmt,codec_name",
        "-of", "json",
        str(path),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        if result.returncode != 0:
            raise ValueError(result.stderr[-1000:])

        streams = json.loads(result.stdout).get("streams", [])
        if not streams:
            raise ValueError("No video stream found.")

        return streams[0]

    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        raise RuntimeError(
            f"Could not validate video output: {path.name}"
        ) from exc


def _escape_filter_value(value: str) -> str:
    """
    Escape a value for use inside an FFmpeg filtergraph.

    Escape backslashes first. Do not surround the resulting path
    with quotes; commas and colons are escaped explicitly.
    """
    return (
        value
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def _build_subtitle_filter(subtitle_path: Path) -> str:
    path = _escape_filter_value(str(subtitle_path.resolve()))
    style = _escape_filter_value(SUBTITLE_STYLE)

    return f"subtitles=filename={path}:force_style={style}"


def render_video(
    clips: list[dict],
    output_name: str = "preview.mp4",
    aspect_ratio: str = "16:9",
    audio_path: str | None = None,
    subtitle_path: str | None = None,
) -> str:
    """Concatenate B-roll clips and render a normalized MP4."""

    if not clips:
        raise ValueError("At least one clip is required.")

    if aspect_ratio not in DIMENSIONS:
        raise ValueError(
            f"Unsupported aspect ratio: {aspect_ratio}. "
            f"Choose from {', '.join(DIMENSIONS)}."
        )

    filename = Path(output_name)
    if (
        not output_name
        or filename.name != output_name
        or filename.suffix.lower() != ".mp4"
    ):
        raise ValueError(
            "Output name must be a plain filename ending in .mp4."
        )

    width, height = DIMENSIONS[aspect_ratio]
    output_path = OUTPUT_DIR / output_name

    if audio_path and not Path(audio_path).is_file():
        raise FileNotFoundError(f"Narration not found: {audio_path}")

    if subtitle_path and not Path(subtitle_path).is_file():
        raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")

    command_inputs = []
    filters = []
    video_labels = []

    for index, clip in enumerate(clips):
        if not isinstance(clip, dict) or "path" not in clip:
            raise ValueError(
                f"Clip {index + 1} must contain a 'path' field."
            )

        clip_path = Path(clip["path"]).resolve()
        if not clip_path.is_file():
            raise FileNotFoundError(f"Clip not found: {clip_path}")

        try:
            duration = float(clip.get("duration_s", 5.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Clip {index + 1} has an invalid duration."
            ) from exc

        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(
                f"Clip {index + 1} must have a finite, positive duration."
            )

        command_inputs.extend(["-i", str(clip_path)])

        filters.append(
            f"[{index}:v]"
            f"trim=duration={duration:.6f},"
            "setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:"
            "force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            "setsar=1,"
            f"fps={FPS},"
            "format=yuv420p,"
            f"settb=AVTB[v{index}]"
        )
        video_labels.append(f"[v{index}]")

    filters.append(
        "".join(video_labels)
        + f"concat=n={len(clips)}:v=1:a=0[outv]"
    )

    video_map = "[outv]"

    if subtitle_path:
        filters.append(
            f"[outv]{_build_subtitle_filter(Path(subtitle_path))}[vout]"
        )
        video_map = "[vout]"

    command = [_ffmpeg_binary(), "-y", *command_inputs]

    audio_input_index = None
    if audio_path:
        audio_input_index = len(clips)
        command.extend(["-i", str(Path(audio_path).resolve())])

    # Write the filtergraph to a temporary file to avoid command-line
    # quoting issues. The filter arguments themselves are escaped above.

    command.extend([
        "-filter_complex",
        ";\n".join(filters),
        "-map", video_map,
    ])

    if audio_input_index is not None:
        command.extend([
            "-map", f"{audio_input_index}:a:0",
            "-c:a", AUDIO_CODEC,
            "-b:a", "192k",
            "-af", "aresample=async=1:first_pts=0",
            "-shortest",
        ])
    else:
        command.append("-an")

    command.extend([
        "-c:v", VIDEO_CODEC,
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        "-movflags", "+faststart",
        str(output_path),
    ])

    _run_command(command)

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg did not produce a valid output file.")

    try:
        video_duration = _probe_duration(output_path)
        stream = _probe_video(output_path)

        if (
            int(stream["width"]) != width
            or int(stream["height"]) != height
        ):
            raise ValueError("Output resolution is incorrect.")

        if stream.get("pix_fmt") != "yuv420p":
            raise ValueError("Output pixel format is incorrect.")

        if audio_path:
            audio_duration = _probe_duration(Path(audio_path))
            if video_duration + 0.15 < audio_duration:
                raise ValueError(
                    "Rendered video is shorter than the narration."
                )

    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Rendered output failed validation: {exc}"
        ) from exc

    return str(output_path)
