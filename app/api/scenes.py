from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.scene_planner import plan_scenes

router = APIRouter(prefix="/api/v1/broll", tags=["Scenes"])


class SceneRequest(BaseModel):
    script: str = Field(min_length=5, max_length=10000)


@router.post("/scenes")
def create_scenes(request: SceneRequest):
    scenes = plan_scenes(request.script)

    if not scenes:
        raise HTTPException(status_code=400, detail="No scenes found")

    return {
        "scene_count": len(scenes),
        "total_duration_s": scenes[-1]["end_s"],
        "scenes": scenes,
    }