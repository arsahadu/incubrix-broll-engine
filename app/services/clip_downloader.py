
import asyncio
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx


OUTPUT_DIR = Path("outputs/assets")
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
ALLOWED_HOST = "pixabay.com"


def _is_approved_url(url: str) -> bool:
    """Allow HTTPS URLs hosted on Pixabay or its subdomains."""
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    return (
        parsed.scheme == "https"
        and bool(hostname)
        and (
            hostname == ALLOWED_HOST
            or hostname.endswith(f".{ALLOWED_HOST}")
        )
    )


async def download_clip(video: dict) -> dict:
    """Download and validate a video returned by Pixabay."""

    video_id = video.get("id")
    url = video.get("preview_url")

    if video_id is None or not url:
        raise ValueError("Video ID and preview URL are required")

    if not _is_approved_url(url):
        raise ValueError("Video URL is not from an approved HTTPS Pixabay host")

    # Use a safe filename rather than trusting an external identifier.
    safe_id = str(video_id)
    if not safe_id.isdigit():
        raise ValueError("Invalid Pixabay video ID")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    destination = OUTPUT_DIR / f"{safe_id}.mp4"
    temporary = OUTPUT_DIR / f"{safe_id}.part"

    # Reuse valid cached files; discard invalid ones.
    if destination.exists():
        try:
            metadata = await asyncio.to_thread(probe_video, destination)
            return {
                "id": video_id,
                "path": str(destination),
                "bytes": destination.stat().st_size,
                **metadata,
                "cached": True,
            }
        except (ValueError, OSError, KeyError, TypeError):
            destination.unlink(missing_ok=True)

    temporary.unlink(missing_ok=True)

    try:
        total = 0

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()

                # Validate the final URL too, because redirects can change hosts.
                if not _is_approved_url(str(response.url)):
                    raise ValueError(
                        "Redirected video URL is not from an approved Pixabay host"
                    )

                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        expected_size = int(content_length)
                    except ValueError as exc:
                        raise ValueError(
                            "Invalid video download size header"
                        ) from exc

                    if expected_size < 0:
                        raise ValueError("Invalid video download size")

                    if expected_size > MAX_DOWNLOAD_BYTES:
                        raise ValueError(
                            "Video exceeds the 100 MB download limit"
                        )

                with temporary.open("wb") as file:
                    async for chunk in response.aiter_bytes(256 * 1024):
                        total += len(chunk)

                        if total > MAX_DOWNLOAD_BYTES:
                            raise ValueError(
                                "Video exceeded the 100 MB download limit"
                            )

                        file.write(chunk)

        if total == 0:
            raise ValueError("Downloaded video is empty")

        # Validate before making the download available to other pipeline steps.
        metadata = await asyncio.to_thread(probe_video, temporary)

        temporary.replace(destination)

        return {
            "id": video_id,
            "path": str(destination),
            "bytes": total,
            **metadata,
            "cached": False,
        }

    finally:
        # Clean up partial downloads after success or failure.
        temporary.unlink(missing_ok=True)


def probe_video(path: Path) -> dict:
    """Validate a video with FFprobe and return technical metadata."""

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries",
                "stream=codec_name,width,height,r_frame_rate:"
                "format=duration",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise ValueError(
            "Could not inspect the downloaded video. Check FFprobe installation."
        ) from exc

    if result.returncode != 0:
        raise ValueError("Downloaded file is not a valid video")

    try:
        data = json.loads(result.stdout)
        streams = data.get("streams", [])

        if not streams:
            raise ValueError("Downloaded file contains no video stream")

        stream = streams[0]
        duration = float(data["format"]["duration"])
        width = int(stream["width"])
        height = int(stream["height"])
        codec = stream["codec_name"]
        frame_rate = stream["r_frame_rate"]

    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "Downloaded file has invalid video metadata"
        ) from exc

    if duration <= 0 or width <= 0 or height <= 0:
        raise ValueError(
            "Video duration and dimensions must be positive"
        )

    return {
        "duration_s": duration,
        "width": width,
        "height": height,
        "codec": codec,
        "frame_rate": frame_rate,
    }
