"""Validation and local transcription for uploaded voiceovers."""
import os
import subprocess
from pathlib import Path

from faster_whisper import WhisperModel

OUTPUT_DIR = Path("outputs")
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a"}
MAX_DURATION_SECONDS = 600


def probe_audio(path: str) -> float:
    """Return audio duration, raising a useful error for invalid media."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True, timeout=30,
        )
        duration = float(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError) as exc:
        raise ValueError("The uploaded file is not a readable audio file.") from exc
    if duration <= 0:
        raise ValueError("The uploaded audio is empty or has no duration.")
    if duration > MAX_DURATION_SECONDS:
        raise ValueError("Audio must be 10 minutes or shorter.")
    return duration


def transcribe_audio(path: str) -> dict:
    """Transcribe with faster-whisper and preserve word/segment timestamps."""
    duration = probe_audio(path)
    model_name = os.getenv("WHISPER_MODEL", "tiny")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    try:
        model = WhisperModel(model_name, device="cpu", compute_type=compute_type)
        segments, info = model.transcribe(
            path, beam_size=3, vad_filter=True, word_timestamps=True
        )
        items = []
        text_parts = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                items.append({"start_s": float(segment.start),
                              "end_s": float(segment.end), "text": text})
                text_parts.append(text)
    except Exception as exc:
        raise RuntimeError(f"Voiceover transcription failed: {exc}") from exc

    transcript = " ".join(text_parts).strip()
    if not transcript:
        raise ValueError(
            "No speech was detected. Upload a voiceover containing clear narration, not silence or music only."
        )
    return {"text": transcript, "segments": items, "duration_s": duration,
            "language": getattr(info, "language", None), "model": model_name}


def align_scene_times(
    scenes: list[dict],
    transcript_segments: list[dict],
    duration: float,
) -> list[dict]:
    """Align scenes to transcript timing with continuous, valid boundaries."""
    if not scenes:
        return scenes

    duration = float(duration)
    if duration <= 0:
        raise ValueError("Audio duration must be positive.")

    scene_count = len(scenes)

    # Prevent impossible timing when there are more scenes than
    # the audio can reasonably accommodate.
    if scene_count > int(duration / 0.5):
        raise ValueError(
            "Too many scenes for this audio duration. Reduce the number of scenes."
        )

    scene_weights = [
        max(1, len(scene.get("text", "").split()))
        for scene in scenes
    ]
    total_weight = sum(scene_weights)

    # Estimate boundaries proportionally if transcription timestamps
    # are unavailable.
    if not transcript_segments:
        cursor = 0.0
        for i, (scene, weight) in enumerate(zip(scenes, scene_weights)):
            end = (
                duration
                if i == scene_count - 1
                else cursor + duration * weight / total_weight
            )
            scene.update(
                start_s=round(cursor, 3),
                end_s=round(end, 3),
                duration_s=round(end - cursor, 3),
            )
            cursor = end
        return scenes

    # Build a cumulative word timeline from Whisper segments.
    segments = [
        segment for segment in transcript_segments
        if segment.get("text", "").strip()
        and float(segment.get("end_s", 0)) > float(segment.get("start_s", 0))
    ]

    if not segments:
        return align_scene_times(scenes, [], duration)

    segment_weights = [
        max(1, len(segment["text"].split()))
        for segment in segments
    ]
    total_segment_words = sum(segment_weights)

    # Use cumulative word proportions to estimate scene boundaries.
    boundaries = [0.0]
    cumulative_scene_words = 0

    for weight in scene_weights[:-1]:
        cumulative_scene_words += weight
        boundaries.append(cumulative_scene_words / total_weight)

    boundaries.append(1.0)

    raw_boundaries = []
    cumulative = 0

    for segment, weight in zip(segments, segment_weights):
        start = max(0.0, float(segment["start_s"]))
        end = min(duration, float(segment["end_s"]))

        raw_boundaries.append(
            (cumulative / total_segment_words, start)
        )
        cumulative += weight

    raw_boundaries.append((1.0, duration))

    def time_at(fraction: float) -> float:
        for i in range(1, len(raw_boundaries)):
            left_fraction, left_time = raw_boundaries[i - 1]
            right_fraction, right_time = raw_boundaries[i]

            if fraction <= right_fraction:
                span = right_fraction - left_fraction
                if span <= 0:
                    return right_time

                ratio = (fraction - left_fraction) / span
                return left_time + ratio * (right_time - left_time)

        return duration

    minimum = 0.5
    cursor = 0.0

    for i, scene in enumerate(scenes):
        if i == scene_count - 1:
            end = duration
        else:
            proposed = time_at(boundaries[i + 1])
            latest_end = duration - minimum * (scene_count - i - 1)
            end = max(cursor + minimum, min(proposed, latest_end))

        scene.update(
            start_s=round(cursor, 3),
            end_s=round(end, 3),
            duration_s=round(end - cursor, 3),
        )
        cursor = end

    return scenes