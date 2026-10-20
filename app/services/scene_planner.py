
import json
import re
import os
import urllib.request
import urllib.error


OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/chat",
)
OLLAMA_MODEL = "llama3.2:3b"


def _fallback_plan(script: str) -> list[dict]:
    """Rule-based planner used when the LLM is unavailable."""

    sentences = re.split(r"(?<=[.!?])\s+", script.strip())
    scenes = []
    current_time = 0.0


    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        duration = max(2.0, len(sentence.split()) / 140 * 60)

        scenes.append({
            "scene_id": len(scenes) + 1,
            "text": sentence,
            "start_s": round(current_time, 2),
            "end_s": round(current_time + duration, 2),
            "duration_s": round(duration, 2),
            "visual_hint": sentence,
            "search_query": sentence[:100],
        })

        current_time += duration

    return scenes


def plan_scenes(script: str) -> list[dict]:
    """Use a local LLM to plan visual scenes, with a safe fallback."""

    if not script or not script.strip():
        return []

    fallback = _fallback_plan(script)

    if not fallback:
        return []


    prompt = f"""
You are an expert B-roll video planner.

Convert the script into a sequence of scenes that can be illustrated
using real stock footage.

Rules:
1. Preserve the original narration exactly and in its original order.
2. Group adjacent sentences only when they share the same visual idea.
3. Create no more than 12 scenes.
4. For each scene, identify the main subject, visible action, and setting. Prefer one visually observable action per scene.
5. Describe footage that could realistically be found in a stock video library.
6. Prefer concrete, observable actions over abstract concepts.
7. Search queries must be 3-6 concrete keywords: subject, visible action, and setting. Avoid full sentences, vague concepts, and adjectives that do not help identify footage.
8. Use the script's actual topic. Do not assume every scene is about agriculture,
   people, or any other particular domain.
9. Do not invent visual details that are unsupported by the script.
10. Return only valid JSON using the exact structure below.
11. Return exactly one scene for each distinct visual idea.
12. Never repeat any scene or narration.
13. For a three-sentence script with three distinct ideas, return three scenes.
14. Do not generate extra scenes to fill a list.

JSON format:
{{
  "scenes": [
    {{
      "text": "Exact narration excerpt from the script",
      "visual_hint": "Subject, visible action, and setting",
      "search_query": "Short, concrete stock footage search terms"
    }}
  ]
}}

SCRIPT:
{script}
"""


    try:
        payload = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "format": "json",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You create accurate, visually grounded B-roll "
                        "plans. Return valid JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "options": {
                "temperature": 0,
                "num_predict": 700,
            },
        }

        request = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))

        content = result["message"]["content"]
        data = json.loads(content)
        planned_scenes = data.get("scenes", [])

        if isinstance(planned_scenes, list):
            planned_scenes = planned_scenes[:12]

        if not isinstance(planned_scenes, list) or not planned_scenes:
            raise ValueError("LLM returned no scenes")

        scenes = []
        current_time = 0.0
        last_position = 0

        for item in planned_scenes:
            if not isinstance(item, dict):
                continue

            text = item.get("text")
            visual_hint = item.get("visual_hint")
            search_query = item.get("search_query")

            if not all(
                isinstance(value, str) and value.strip()
                for value in (text, visual_hint, search_query)
            ):
                continue
            text = text.strip()

            position = script.find(text, last_position)

            if position == -1:
                raise ValueError(
                    "Scene narration is duplicated, out of order, "
                    "or not an exact script excerpt"
                )

            last_position = position + len(text)

            # Estimate duration from narration text.
            duration = max(2.0, len(text.split()) / 140 * 60)

            scenes.append({
                "scene_id": len(scenes) + 1,
                "text": text.strip(),
                "start_s": round(current_time, 2),
                "end_s": round(current_time + duration, 2),
                "duration_s": round(duration, 2),
                "visual_hint": visual_hint.strip(),
                "search_query": search_query.strip(),
            })

            current_time += duration

        if not scenes:
            raise ValueError("LLM returned no valid scene entries")

        print(f"Scene planner: Ollama generated {len(scenes)} scenes")
        return scenes

    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        print(f"Scene planner: using fallback ({exc})")
        return fallback
