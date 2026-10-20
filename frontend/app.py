import json
import os
import time
from pathlib import Path

import requests
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_URL = os.getenv("BROLL_API_URL", "http://127.0.0.1:8000").rstrip("/")
POLL_INTERVAL = 2
MAX_WAIT_SECONDS = 1200

st.set_page_config(page_title="B-Roll Studio", page_icon="🎬", layout="wide")

st.markdown("""
<style>
.block-container {max-width: 1080px; padding-top: 2rem;}
.hero {padding: 1.5rem; border-radius: 18px; margin-bottom: 1rem;
background: linear-gradient(120deg, rgba(100,80,220,.16), rgba(40,180,160,.10));
border: 1px solid rgba(128,128,128,.25);}
div[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.22);
border-radius: 12px; padding: .8rem;}
</style>
""", unsafe_allow_html=True)


def api_request(method, endpoint, **kwargs):
    try:
        response = requests.request(
            method, f"{API_URL}{endpoint}",
            timeout=kwargs.pop("timeout", 30), **kwargs
        )
        if not response.ok:
            try:
                body = response.json()
                detail = (
                    body.get("error", {}).get("message")
                    or body.get("detail")
                    or response.text
                )
            except (ValueError, AttributeError):
                detail = response.text

            raise RuntimeError(
                f"API error ({response.status_code}): {detail}"
            )

        return response.json()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Can't reach the API at {API_URL}. Check that FastAPI is running."
        ) from exc


def resolve_output(raw_path):
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    return path if path.is_relative_to(PROJECT_ROOT) and path.is_file() else None


def download_file(label, raw_path, mime):
    path = resolve_output(raw_path)
    if path is None:
        st.caption(f"{label} unavailable")
        return
    st.download_button(
        f"Download {label}", path.read_bytes(), file_name=path.name,
        mime=mime, key=f"download_{path.name}", use_container_width=True
    )


def render_results(result):
    outputs = result.get("outputs", [])
    if not outputs:
        st.warning("The job completed, but no video files were returned.")
        return

    st.markdown("## Your video is ready")
    tabs = st.tabs([item.get("aspect_ratio", "Video") for item in outputs])
    for tab, output in zip(tabs, outputs):
        with tab:
            path = resolve_output(output.get("path"))
            if path is None:
                st.error(f"Video file not found: {output.get('path')}")
                continue
            st.video(path.read_bytes())
            st.caption(f"{path.stat().st_size / (1024 * 1024):.1f} MB")
            download_file(f"{output.get('aspect_ratio', '')} MP4", str(path), "video/mp4")

    st.markdown("### Project files")
    cols = st.columns(3)
    artifacts = [
        (cols[0], "Captions (SRT)", result.get("captions_path"), "text/plain"),
        (cols[1], "Timeline (JSON)", result.get("timeline_path"), "application/json"),
        (cols[2], "Footage manifest (JSON)", result.get("manifest_path"), "application/json"),
    ]
    for col, label, path, mime in artifacts:
        with col:
            download_file(label, path, mime)

    manifest_path = resolve_output(result.get("manifest_path"))
    with st.expander("Footage sources & attribution"):
        if not manifest_path:
            st.caption("Manifest unavailable.")
            return
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st.warning("Could not read the footage manifest.")
            return
        st.caption(f"Unique assets: {manifest.get('unique_asset_count', 0)}")
        for asset in manifest.get("assets", []):
            st.markdown(f"**{asset.get('provider', 'Stock footage')}** · {asset.get('creator', 'Creator not listed')}")
            if asset.get("tags"):
                st.caption(f"Tags: {asset['tags']}")
            if asset.get("page_url"):
                st.markdown(f"[View original source]({asset['page_url']})")
            st.divider()


def poll_job(job_id, progress, message):
    started = time.monotonic()
    errors = 0
    while time.monotonic() - started < MAX_WAIT_SECONDS:
        try:
            job = api_request("GET", f"/api/v1/broll/jobs/{job_id}", timeout=15)
            errors = 0
        except RuntimeError:
            errors += 1
            if errors >= 10:
                message.error(f"Connection lost. Your job may still be running. Job ID: {job_id}")
                return None
            message.warning(f"Reconnecting to the API… ({errors}/10)")
            time.sleep(min(POLL_INTERVAL * errors, 10))
            continue

        status = job.get("status", "processing")
        progress.progress(max(0, min(int(job.get("progress", 0)), 100)))
        message.info(job.get("message", status.title()))
        if status == "completed":
            progress.progress(100)
            message.success("Your video is ready!")
            return job
        if status == "failed":
            message.error(job.get("message", "Video generation failed."))
            return job
        time.sleep(POLL_INTERVAL)

    message.warning("This is taking longer than expected. You can check the job ID again.")
    return None


if "last_job_id" not in st.session_state:
    st.session_state["last_job_id"] = ""
if "last_job_result" not in st.session_state:
    st.session_state["last_job_result"] = None

header, status_col = st.columns([10, 3])
with header:
    st.markdown("""
    <div class="hero">
      <div style="font-size:.8rem;letter-spacing:.12em;font-weight:700;">CREATION ENGINE</div>
      <h1 style="margin:.4rem 0;">🎬 B-Roll Studio</h1>
      <p style="margin:0;">Script or voiceover to A Narrated Video.</p>
    </div>
    """, unsafe_allow_html=True)
with status_col:
    st.write("")
    try:
        api_request("GET", "/health", timeout=5)
        st.success("API connected")
    except RuntimeError:
        st.error("API offline")
        st.caption("Start FastAPI to generate a video.")

st.markdown("### 1. Add narration")
st.caption("Start with a written script or upload an existing voiceover.")

sample = ("A new day begins at college. Students walk across campus as the morning sun rises. "
          "Inside the classroom, students listen, learn, and share ideas. During lunch, friends "
          "gather at the canteen, enjoying food and laughter. At the end of the day, students "
          "head home with new memories.")
if st.button("Use sample script"):
    st.session_state["script_input"] = sample

input_mode = st.radio(
    "Narration source",
    ["Write a script", "Upload voiceover"],
    horizontal=True,
    key="narration_source",
)

script = ""
audio_file = None

if input_mode == "Write a script":
    script = st.text_area(
        "Script",
        key="script_input",
        height=160,
        max_chars=12000,
        placeholder="Paste or write your narration here…",
        label_visibility="collapsed",
    )
else:
    audio_file = st.file_uploader(
        "Voiceover file (MP3, WAV, M4A)",
        type=["mp3", "wav", "m4a"],
        help="Maximum duration: 10 minutes.",
        key="voiceover_upload",
    )

with st.form("video_generation_form"):
    st.markdown("### 2. Choose your output")

    col1, col2 = st.columns([2, 1])

    # Keep your existing format/style settings here.
    formats = st.multiselect(
    "Video format",
    ["16:9", "9:16", "1:1"],
    default=["16:9"],
    help="16:9 YouTube · 9:16 Shorts/Reels · 1:1 square posts",
)
    burn_in = st.checkbox(
    "Burn captions into the video",
    value=True,
    help="Display subtitles directly on the video.",
)
    submitted = st.form_submit_button("Generate video")



if submitted:
    if not formats:
        st.error("Choose at least one video format.")

    elif input_mode == "Write a script" and not script.strip():
        st.error("Please enter a script.")

    elif input_mode == "Upload voiceover" and audio_file is None:
        st.error("Please upload a voiceover file.")

    else:
        avoid_text = st.session_state.get("avoid_text", "")
        avoid_terms = [
            term.strip()
            for term in avoid_text.split(",")
            if term.strip()
        ]

        captions = {
            "burn_in": burn_in,
            "srt": True,
        }

        try:
            with st.spinner("Starting your video job…"):

                if input_mode == "Write a script":
                    payload = {
                        "script": script.strip(),
                        "aspect_ratios": formats,
                        "avoid": avoid_terms,
                        "captions": captions,
                    }

                    created = api_request(
                        "POST",
                        "/api/v1/broll/jobs",
                        json=payload,
                        timeout=60,
                    )

                else:
                    params = [
                        ("filename", audio_file.name),
                        ("burn_in", str(burn_in).lower()),
                    ]

                    params.extend(
                        ("aspect_ratios", ratio)
                        for ratio in formats
                    )

                    params.extend(
                        ("avoid", term)
                        for term in avoid_terms
                    )

                    created = api_request(
                        "POST",
                        "/api/v1/broll/jobs/audio-upload",
                        params=params,
                        data=audio_file.getvalue(),
                        headers={
                            "Content-Type": (
                                audio_file.type
                                or "application/octet-stream"
                            )
                        },
                        timeout=60,
                    )

            job_id = created["job_id"]
            st.session_state["last_job_id"] = job_id
            st.session_state["last_job_result"] = None

            st.markdown("### 3 · Making your video")
            st.caption(f"Job ID: `{job_id}`")

            progress = st.progress(0)
            message = st.empty()

            result = poll_job(job_id, progress, message)

            if result and result.get("status") == "completed":
                st.session_state["last_job_result"] = result

            elif result and result.get("status") == "failed":
                st.error(
                    result.get("error")
                    or result.get("message")
                    or "Video generation failed."
                )

        except (
            RuntimeError,
            KeyError,
            ValueError,
            requests.RequestException,
        ) as exc:
            st.error(str(exc))



with st.expander("Already started a job? Check its status"):
    job_id = st.text_input("Job ID", value=st.session_state.get("last_job_id", ""), placeholder="Paste your job ID")
    if st.button("Check job status"):
        if not job_id.strip():
            st.warning("Enter a job ID first.")
        else:
            try:
                result = api_request("GET", f"/api/v1/broll/jobs/{job_id.strip()}", timeout=15)
                st.session_state["last_job_id"] = job_id.strip()
                if result.get("status") == "completed":
                    st.session_state["last_job_result"] = result
                    st.success("Found your completed video.")
                else:
                    st.info(f"{result.get('status', 'processing').title()} — {result.get('message', 'Still working')}")
            except RuntimeError as exc:
                st.error(str(exc))

if st.session_state.get("last_job_result"):
    st.divider()
    render_results(st.session_state["last_job_result"])

st.divider()
st.caption("FastAPI · faster-whisper transcription · AI-assisted scene planning · Pixabay stock footage · FFmpeg rendering")