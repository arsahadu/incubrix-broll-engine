
import hashlib
import json
import os
import shutil
import threading
from pathlib import Path
from uuid import uuid4
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas.request import BrollRequest
from app.api.footage import router as footage_router
from app.api.download import router as download_router
from app.api.scenes import router as scenes_router
from app.api.render import router as render_router
from app.services.pipeline import run_pipeline
from app.services.audio_input import ALLOWED_EXTENSIONS, MAX_DURATION_SECONDS


app = FastAPI(title="IncuBrix B-roll Engine", version="0.3.0")
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,
)
app.include_router(footage_router)
app.include_router(download_router)
app.include_router(scenes_router)
app.include_router(render_router)

jobs = {}
idempotency_records = {}
jobs_lock = threading.Lock()


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    message = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": message,
            }
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "details": exc.errors(),
            }
        },
    )


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _register_job(
    job_id: str,
    job_request: BrollRequest,
    audio_path: str | None,
    message: str,
    key: str | None,
    fingerprint: str,
):
    if key and (len(key) > 200 or not key.strip()):
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key must contain 1–200 characters.",
        )

    with jobs_lock:
        if key and key in idempotency_records:
            record = idempotency_records[key]
            if record["fingerprint"] != fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was reused with a different request.",
                )
            return record["job_id"], False

        jobs[job_id] = {
            "job_id": job_id,
            "status": "accepted",
            "progress": 0,
            "message": message,
            "request": job_request.model_dump(),
            "uploaded_audio_path": audio_path,
        }

        if key:
            idempotency_records[key] = {
                "fingerprint": fingerprint,
                "job_id": job_id,
            }

        return job_id, True


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/ready")
def ready():
    def available(binary: str) -> bool:
        path = Path(binary)
        if path.is_absolute() or path.parent != Path("."):
            return path.is_file() and os.access(path, os.X_OK)
        return shutil.which(binary) is not None

    missing = [
        name
        for name, binary in (
            ("ffmpeg", os.getenv("FFMPEG_BINARY", "ffmpeg")),
            ("ffprobe", os.getenv("FFPROBE_BINARY", "ffprobe")),
        )
        if not available(binary)
    ]

    if missing:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "missing_dependencies": missing},
        )

    return {"status": "ready"}


@app.post("/api/v1/broll/jobs", status_code=202)
@limiter.limit("5/minute")
def create_job(
    request: BrollRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    job_id = str(uuid4())
    fingerprint = _fingerprint(request.model_dump())

    actual_id, created = _register_job(
        job_id,
        request,
        None,
        "Job accepted",
        idempotency_key,
        fingerprint,
    )

    if created:
        background_tasks.add_task(run_pipeline, actual_id, request, jobs)

    return {
        "job_id": actual_id,
        "status": jobs[actual_id]["status"],
        "message": (
            "Video generation started"
            if created
            else "Returning existing job for this idempotency key"
        ),
    }



@app.get("/api/v1/broll/jobs/{job_id}")
def get_job(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)

        if job is None:
            raise HTTPException(
                status_code=404,
                detail="Job not found",
            )

        # Expose only fields required by the UI.
        public_fields = (
            "job_id",
            "status",
            "progress",
            "message",
            "outputs",
            "captions_path",
            "timeline_path",
            "manifest_path",
            "error",
            "scenes",
        )

        return {
            key: job[key]
            for key in public_fields
            if key in job
        }

@app.post("/api/v1/broll/jobs/audio-upload", status_code=202)
async def create_audio_upload_job(
    request: Request,
    background_tasks: BackgroundTasks,
    filename: str,
    aspect_ratios: list[str] | None = None,
    avoid: list[str] | None = None,
    burn_in: bool = True,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Upload MP3, WAV, or M4A audio.",
        )

    aspect_ratios = aspect_ratios or ["16:9"]
    avoid = avoid or []

    allowed_ratios = {"16:9", "9:16", "1:1"}
    if not aspect_ratios or any(r not in allowed_ratios for r in aspect_ratios):
        raise HTTPException(
            status_code=400,
            detail="Choose valid aspect ratios: 16:9, 9:16, or 1:1.",
        )

    max_mb = int(os.getenv("MAX_AUDIO_UPLOAD_MB", "100"))
    if max_mb <= 0:
        raise HTTPException(status_code=500, detail="Invalid upload size configuration.")

    max_bytes = max_mb * 1024 * 1024
    audio_bytes = await request.body()

    if not audio_bytes:
        raise HTTPException(status_code=400, detail="The uploaded audio file is empty.")
    if len(audio_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Audio upload exceeds {max_mb} MB.",
        )

    # Fingerprint the bytes and options so retries don't create duplicate jobs.
    fingerprint = _fingerprint({
        "filename": filename,
        "audio_sha256": hashlib.sha256(audio_bytes).hexdigest(),
        "aspect_ratios": aspect_ratios,
        "avoid": avoid,
        "burn_in": burn_in,
    })

    if idempotency_key:
        with jobs_lock:
            existing = idempotency_records.get(idempotency_key)
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency-Key was reused with a different request.",
                    )
                return {
                    "job_id": existing["job_id"],
                    "status": jobs[existing["job_id"]]["status"],
                    "message": "Returning existing job for this idempotency key",
                }

    job_id = str(uuid4())
    upload_dir = Path(os.getenv("BROLL_UPLOAD_DIR", "outputs/uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)
    audio_path = upload_dir / f"{job_id}{extension}"

    try:
        audio_path.write_bytes(audio_bytes)

        job_request = BrollRequest(
            script="__uploaded_audio__",
            aspect_ratios=aspect_ratios,
            avoid=avoid,
            captions={"burn_in": burn_in, "srt": True},
        )

        actual_id, created = _register_job(
            job_id,
            job_request,
            str(audio_path),
            "Audio uploaded; job accepted",
            idempotency_key,
            fingerprint,
        )

        if not created:
            audio_path.unlink(missing_ok=True)
            return {
                "job_id": actual_id,
                "status": jobs[actual_id]["status"],
                "message": "Returning existing job for this idempotency key",
            }

        background_tasks.add_task(run_pipeline, actual_id, job_request, jobs)

        return {
            "job_id": actual_id,
            "status": "accepted",
            "message": "Audio video generation started",
        }

    except Exception:
        audio_path.unlink(missing_ok=True)
        raise
