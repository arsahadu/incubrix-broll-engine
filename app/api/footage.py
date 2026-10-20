from fastapi import APIRouter, HTTPException, Query
import httpx
from app.services.footage_search import search_videos

router = APIRouter(prefix="/api/v1/broll", tags=["Footage"])


@router.get("/search")
async def search_footage(
    q: str = Query(min_length=2, max_length=100),
    per_page: int = Query(default=5, ge=3, le=10),
):
    try:
        results = await search_videos(q, per_page)
        return {
            "query": q,
            "count": len(results),
            "results": results,
        }
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Pixabay footage search failed",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc