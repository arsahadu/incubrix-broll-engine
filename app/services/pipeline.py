import json
import subprocess
from pathlib import Path

from app.services.scene_planner import plan_scenes
from app.services.footage_search import search_videos
from app.services.clip_downloader import download_clip
from app.services.renderer import render_video
from app.services.narration import generate_narration, write_srt
from app.services.audio_input import transcribe_audio, align_scene_times, probe_audio

OUTPUT_DIR = Path("outputs")
MIN_RELEVANCE_SCORE = 0.25


def _avoid_match(candidate: dict, avoid_terms: set[str]) -> bool:
    """Return True when a candidate's tags contain a blocked term."""
    if not avoid_terms:
        return False
    tags = {
        word.strip(".,;:!?()[]{}\\\"'").lower()
        for tag in (candidate.get("tags") or "").split(",")
        for word in tag.split()
        if word.strip()
    }
    return bool(avoid_terms & tags)


async def _find_clip_for_scene(
    scene: dict,
    scene_index: int,
    used_ids: set,
    avoid_terms: set[str],
) -> tuple[dict, dict] | tuple[None, None]:
    """Search multiple query variants, then download the best unique match."""
    query = (
        scene.get("search_query")
        or scene.get("visual_hint")
        or scene.get("text", "")
    ).strip()
    visual_hint = (scene.get("visual_hint") or "").strip()
    if not query:
        return None, None

    # Prefer concise stock-search terms; use the visual description as a fallback.
    queries = list(dict.fromkeys(
        value for value in (query, visual_hint) if value
    ))
    candidates_by_id = {}

    for search_query in queries:
        results = await search_videos(
            search_query,
            per_page=10,
            visual_hint=visual_hint,
        )
        for candidate in results:
            asset_id = candidate.get("id")
            if asset_id is None or asset_id in used_ids:
                continue
            if candidate.get("relevance_score", 0) < MIN_RELEVANCE_SCORE:
                continue
            if _avoid_match(candidate, avoid_terms):
                continue

            candidate = {**candidate, "search_query_used": search_query}
            previous = candidates_by_id.get(asset_id)
            if (
                previous is None
                or candidate.get("relevance_score", 0)
                > previous.get("relevance_score", 0)
            ):
                candidates_by_id[asset_id] = candidate

    ranked = sorted(
        candidates_by_id.values(),
        key=lambda item: item.get("relevance_score", 0),
        reverse=True,
    )

    for candidate in ranked:
        try:
            downloaded = await download_clip(candidate)
            return candidate, downloaded
        except (ValueError, RuntimeError, OSError) as exc:
            print(
                f"Skipping clip {candidate.get('id')} for scene "
                f"{scene_index}: {exc}"
            )

    return None, None



async def run_pipeline(job_id: str, request, jobs: dict):
    """Generate narrated B-roll videos with ranked, unique stock footage."""
    try:
        job = jobs[job_id]
        job.update(
            status="processing",
            progress=3,
            message="Preparing narration",
        )

        audio_path = job.get("uploaded_audio_path")
        transcript_data = None

        # 1. Prepare narration and plan scenes.
        if audio_path:
            job.update(
                progress=8,
                message="Transcribing uploaded voiceover",
            )
            transcript_data = transcribe_audio(audio_path)
            script_text = transcript_data["text"]
            scenes = request.scenes or plan_scenes(script_text)
            scenes = align_scene_times(
                scenes,
                transcript_data["segments"],
                transcript_data["duration_s"],
            )
        elif request.audio_url:
            raise ValueError(
                "Remote audio URL ingestion is not enabled yet. "
                "Upload the audio file in B-roll Studio."
            )
        else:
            script_text = request.script or " ".join(
                scene.get("text", "")
                for scene in (request.scenes or [])
            )
            scenes = request.scenes or plan_scenes(script_text)

        if not scenes:
            raise ValueError("No usable scenes were provided.")

        job.update(
            progress=15,
            message="Searching for stock footage",
        )

        selected_clips = []
        used_ids = set()
        scene_records = []
        asset_records = []

        avoid_terms = {
            word.strip(".,;:!?()[]{}\\\"'").lower()
            for term in (request.avoid or [])
            for word in term.split()
            if word.strip()
        }

        # 2. Find and download unique footage for each scene.
        for index, scene in enumerate(scenes, start=1):
            chosen, downloaded = await _find_clip_for_scene(
                scene,
                index,
                used_ids,
                avoid_terms,
            )

            if chosen is None or downloaded is None:
                raise RuntimeError(
                    f"No suitable unique downloadable footage found "
                    f"for scene {index}: {scene.get('text', '')}. "
                    "Try a more concrete visual description."
                )

            used_ids.add(chosen["id"])

            chosen_query = (
                chosen.get("search_query_used")
                or chosen.get("search_query")
                or scene.get("search_query")
                or scene.get("visual_hint")
                or scene.get("text", "")
            )

            scene_record = {
                **scene,
                "scene_id": scene.get("scene_id", index),
                "search_query_used": chosen_query,
                "asset_id": chosen["id"],
                "asset_path": downloaded["path"],
                "asset_source_url": chosen.get("page_url"),
                "asset_creator": chosen.get("user"),
                "relevance_score": chosen.get("relevance_score", 0),
                "semantic_score": chosen.get("semantic_score", 0),
                "keyword_match": chosen.get("keyword_match", 0),
            }
            scene_records.append(scene_record)

            selected_clips.append({
                "path": downloaded["path"],
                "duration_s": float(scene.get("duration_s") or 1.0),
            })

            asset_records.append({
                "id": chosen["id"],
                "provider": "Pixabay",
                "page_url": chosen.get("page_url"),
                "source_url": chosen.get("preview_url"),
                "creator": chosen.get("user"),
                "tags": chosen.get("tags", ""),
                "search_query_used": chosen_query,
                "duration_s": downloaded.get("duration_s"),
                "local_path": downloaded["path"],
                "relevance_score": chosen.get("relevance_score", 0),
                "semantic_score": chosen.get("semantic_score", 0),
                "keyword_match": chosen.get("keyword_match", 0),
                "license": "Pixabay Content License",
                "license_note": (
                    "Confirm the current license and usage restrictions "
                    "before commercial publication."
                ),
            })

            progress = 15 + int(55 * index / len(scenes))
            job.update(
                progress=min(progress, 70),
                message=(
                    f"Found footage for scene {index} of {len(scenes)}"
                ),
            )

        if not selected_clips:
            raise RuntimeError("No suitable footage could be downloaded.")

        # 3. Prepare output artifact paths.
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        timeline_path = OUTPUT_DIR / f"{job_id}_timeline.json"
        manifest_path = OUTPUT_DIR / f"{job_id}_manifest.json"
        srt_output_path = OUTPUT_DIR / f"{job_id}_captions.srt"

        input_type = "uploaded_audio" if audio_path else "script_or_scenes"

        timeline = {
            "job_id": job_id,
            "script": script_text,
            "input_type": input_type,
            "transcription": (
                {
                    "provider": "faster-whisper",
                    "model": transcript_data["model"],
                    "language": transcript_data["language"],
                }
                if transcript_data else None
            ),
            "scenes": scene_records,
            "note": (
                "Scene boundaries are estimated from transcription "
                "segment timestamps and continuous timeline constraints."
                if transcript_data
                else "Scene durations are weighted by explicit duration "
                     "or scene text length and scaled to generated narration."
            ),
        }

        manifest = {
            "job_id": job_id,
            "assets": asset_records,
            "unique_asset_count": len(asset_records),
            "source": "Pixabay",
            "input_type": input_type,
            "transcription": (
                {
                    "provider": "faster-whisper",
                    "model": transcript_data["model"],
                    "language": transcript_data["language"],
                }
                if transcript_data else None
            ),
            "original_audio_preserved": bool(transcript_data),
            "warnings": [],
        }

        # 4. Prepare original or generated narration.
        if audio_path:
            job.update(
                progress=75,
                message="Preparing original voiceover for rendering",
            )
            audio_duration = probe_audio(audio_path)
        else:
            job.update(
                progress=75,
                message="Generating narration",
            )

            narration_script = request.script or " ".join(
                scene.get("text", "")
                for scene in scene_records
            )

            audio_path = generate_narration(
                narration_script,
                voice=getattr(request, "voice", None) or "Aman",
            )

            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    audio_path,
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )

            audio_duration = float(probe.stdout.strip())

            if audio_duration <= 0:
                raise RuntimeError(
                    "Generated narration has invalid duration."
                )

        # 5. Allocate a continuous timeline covering the audio.
        scene_count = len(scene_records)
        min_scene_duration = 0.1

        if audio_duration < scene_count * min_scene_duration:
            raise RuntimeError(
                "There are too many scenes for the narration duration. "
                "Reduce the number of scenes."
            )

        weights = []

        for scene in scene_records:
            try:
                requested_duration = float(
                    scene.get("duration_s") or 0
                )
            except (TypeError, ValueError):
                requested_duration = 0.0

            if requested_duration > 0:
                weights.append(requested_duration)
            else:
                weights.append(
                    float(max(1, len(scene.get("text", "").split())))
                )

        total_weight = sum(weights)

        if total_weight <= 0:
            raise RuntimeError(
                "Could not determine scene timing weights."
            )

        cursor = 0.0

        for index, (scene, clip, weight) in enumerate(
            zip(scene_records, selected_clips, weights)
        ):
            is_last = index == scene_count - 1

            if is_last:
                end = audio_duration
            elif transcript_data:
                proposed_end = float(
                    scene.get(
                        "end_s",
                        cursor + audio_duration * weight / total_weight,
                    )
                )

                latest_end = (
                    audio_duration
                    - (scene_count - index - 1) * min_scene_duration
                )

                end = max(
                    cursor + min_scene_duration,
                    min(proposed_end, latest_end),
                )
            else:
                end = cursor + audio_duration * weight / total_weight

            end = min(end, audio_duration)
            duration = end - cursor

            if duration < min_scene_duration - 0.001:
                raise RuntimeError(
                    f"Scene {index + 1} has an invalid duration."
                )

            scene["start_s"] = round(cursor, 3)
            scene["end_s"] = round(end, 3)
            scene["duration_s"] = round(duration, 3)

            clip["duration_s"] = scene["duration_s"]
            cursor = end

        # Set the final boundary to the exact narration duration.
        scene_records[-1]["end_s"] = round(audio_duration, 3)
        scene_records[-1]["duration_s"] = round(
            audio_duration - scene_records[-1]["start_s"],
            3,
        )
        selected_clips[-1]["duration_s"] = (
            scene_records[-1]["duration_s"]
        )

        # Validate continuity and full narration coverage.
        expected_start = 0.0

        for index, scene in enumerate(scene_records, start=1):
            start = float(scene["start_s"])
            end = float(scene["end_s"])

            if abs(start - expected_start) > 0.01 or end <= start:
                raise RuntimeError(
                    f"Invalid scene timeline at scene {index}."
                )

            expected_start = end

        if abs(expected_start - audio_duration) > 0.01:
            raise RuntimeError(
                "Scene timeline does not cover the complete narration."
            )

        # 6. Write final timeline and captions.
        timeline["scenes"] = scene_records
        timeline["audio_duration_s"] = round(audio_duration, 3)

        timeline_path.write_text(
            json.dumps(timeline, indent=2),
            encoding="utf-8",
        )

        srt_path = write_srt(
            scene_records,
            str(srt_output_path),
        )

        # 7. Render all requested aspect ratios.
        job.update(
            progress=80,
            message="Rendering requested formats",
        )

        rendered_outputs = []

        for ratio in request.aspect_ratios:
            suffix = ratio.replace(":", "x")

            output_path = render_video(
                selected_clips,
                output_name=f"{job_id}_{suffix}.mp4",
                aspect_ratio=ratio,
                audio_path=audio_path,
                subtitle_path=(
                    srt_path
                    if request.captions.get("burn_in", False)
                    else None
                ),
            )

            rendered_outputs.append({
                "aspect_ratio": ratio,
                "path": output_path,
            })

        # 8. Save final manifest after outputs are known.
        manifest["audio_duration_s"] = round(audio_duration, 3)
        manifest["aspect_ratios"] = list(request.aspect_ratios)
        manifest["outputs"] = rendered_outputs
        manifest["scenes"] = [
            {
                "scene_id": scene["scene_id"],
                "asset_id": scene["asset_id"],
                "start_s": scene["start_s"],
                "end_s": scene["end_s"],
                "duration_s": scene["duration_s"],
                "search_query_used": scene["search_query_used"],
            }
            for scene in scene_records
        ]

        manifest_path.write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )

        # 9. Report job completion using the existing response structure.
        job.update(
            status="completed",
            progress=100,
            message="Video rendering completed",
            scenes=scene_records,
            outputs=rendered_outputs,
            timeline_path=str(timeline_path),
            manifest_path=str(manifest_path),
            audio_path=audio_path,
            captions_path=srt_path,
            transcript=script_text,
            input_type=input_type,
        )

    except Exception as exc:
        job = jobs.get(job_id)
        if job is not None:
            job.update(
                status="failed",
                message=str(exc),
            )
