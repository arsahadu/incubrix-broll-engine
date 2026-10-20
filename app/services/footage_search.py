
import os
import re
from functools import lru_cache

import httpx
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
PIXABAY_API_URL = "https://pixabay.com/api/videos/"
MAX_QUERY_LENGTH = 100

STOP_WORDS = {
    "a", "an", "and", "at", "by", "for", "from", "in", "into", "of",
    "on", "or", "the", "to", "with", "is", "are", "as",
}

load_dotenv()


def normalize_search_query(query: str, max_length: int = MAX_QUERY_LENGTH) -> str:
    """Normalize a scene description into a concise Pixabay search query."""
    query = re.sub(r"[^\w\s-]", " ", query or "")
    words = query.split()

    # Avoid sending an entire narration sentence to Pixabay.
    normalized = " ".join(words[:8])
    return normalized[:max_length].strip()


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """Load the embedding model once and reuse it."""
    return SentenceTransformer(MODEL_NAME)


def _keywords(text: str) -> set[str]:
    """Return useful lowercase terms for a lightweight lexical match."""
    return {
        word
        for word in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(word) > 1 and word not in STOP_WORDS
    }


def _rank_hits(
    query: str,
    visual_hint: str,
    hits: list[dict],
) -> list[dict]:
    """Rank Pixabay results using semantic and keyword relevance."""
    candidates = []

    for hit in hits:
        videos = hit.get("videos") or {}
        video = videos.get("medium") or videos.get("small")

        if not video or not video.get("url") or hit.get("id") is None:
            continue

        tags = hit.get("tags") or ""

        candidates.append({
            "id": hit.get("id"),
            "tags": tags,
            "duration_s": hit.get("duration"),
            "width": video.get("width"),
            "height": video.get("height"),
            "preview_url": video.get("url"),
            "thumbnail": video.get("thumbnail"),
            "page_url": hit.get("pageURL"),
            "user": hit.get("user"),
        })

    if not candidates:
        return []

    scoring_text = " ".join(
        part.strip()
        for part in (visual_hint, query)
        if part and part.strip()
    ).strip()

    if not scoring_text:
        scoring_text = query

    tag_texts = [
        item["tags"] or "unknown footage"
        for item in candidates
    ]

    model = get_embedding_model()

    query_embedding = model.encode(
        [scoring_text],
        convert_to_tensor=True,
        normalize_embeddings=True,
    )
    tag_embeddings = model.encode(
        tag_texts,
        convert_to_tensor=True,
        normalize_embeddings=True,
    )

    semantic_scores = cos_sim(
        query_embedding,
        tag_embeddings,
    )[0].tolist()

    wanted = _keywords(scoring_text)

    for item, semantic in zip(candidates, semantic_scores):
        tag_words = _keywords(item["tags"])
        lexical = len(wanted & tag_words) / max(1, len(wanted))

        item["semantic_score"] = round(float(semantic), 4)
        item["keyword_match"] = round(lexical, 4)
        item["relevance_score"] = round(
            0.8 * float(semantic) + 0.2 * lexical,
            4,
        )

    candidates.sort(
        key=lambda item: item["relevance_score"],
        reverse=True,
    )

    return candidates


async def search_videos(
    query: str,
    per_page: int = 10,
    visual_hint: str | None = None,
) -> list[dict]:
    """Search Pixabay and rank results against the intended scene."""
    api_key = os.getenv("PIXABAY_API_KEY")

    if not api_key:
        raise RuntimeError("PIXABAY_API_KEY is not configured")

    # Normalize before sending the query to Pixabay.
    query = normalize_search_query(query)

    if not query:
        return []

    params = {
        "key": api_key,
        "q": query,
        "per_page": max(3, min(per_page, 20)),
        "safesearch": "true",
    }

    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
    ) as client:
        response = await client.get(
            PIXABAY_API_URL,
            params=params,
        )

        if response.is_error:
            # Do not expose the API key by printing the full request URL.
            error_body = response.text[:500]
            raise RuntimeError(
                f"Pixabay API returned HTTP {response.status_code}: "
                f"{error_body}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Pixabay returned an invalid JSON response."
            ) from exc

    results = _rank_hits(
        query,
        visual_hint or "",
        data.get("hits", []),
    )

    for item in results:
        item["search_query"] = query

    return results
