from fastapi import APIRouter, HTTPException, Query

from app.services.footage_search import search_videos
from app.services.clip_downloader import download_clip

router = APIRouter(prefix="/api/v1/broll", tags=["Downloads"])


@router.post("/download")
async def download_footage(
    q: str = Query(min_length=2, max_length=100),
):
    try:
        videos = await search_videos(q, per_page=5)

        for video in videos:
            try:
                return await download_clip(video)
            except Exception:
                continue

        raise HTTPException(
            status_code=404,
            detail="No downloadable, valid videos were found",
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Footage search or download failed",
        ) from exc