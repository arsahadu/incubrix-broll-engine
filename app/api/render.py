from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.renderer import render_video

router = APIRouter(prefix="/api/v1/broll", tags=["Rendering"])


class RenderRequest(BaseModel):
    clip_paths: list[str] = Field(min_length=1)
    aspect_ratio: str = "16:9"


@router.post("/render")
def create_render(request: RenderRequest):
    try:
        clips = [{"path": path} for path in request.clip_paths]
        filename = "preview.mp4"

        output = render_video(
            clips,
            output_name=filename,
            aspect_ratio=request.aspect_ratio,
        )

        return {
            "status": "completed",
            "output_path": output,
            "message": "Video rendered successfully",
        }

    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc