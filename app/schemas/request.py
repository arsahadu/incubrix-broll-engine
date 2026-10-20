from typing import Literal
from pydantic import BaseModel, Field, model_validator


class BrollRequest(BaseModel):
    audio_url: str | None = None
    script: str | None = None
    scenes: list[dict] | None = None

    voice: str = "en-IN-female"
    aspect_ratios: list[Literal["16:9", "9:16", "1:1"]] = [
        "16:9", "9:16"
    ]
    style: str = "bright, modern, real-world footage"
    avoid: list[str] = []
    captions: dict = {"burn_in": True, "srt": True}

    @model_validator(mode="after")
    def validate_input(self):
        if not self.audio_url and not self.script and not self.scenes:
            raise ValueError(
                "Provide audio_url, script, or scenes"
            )
        if not self.aspect_ratios:
            raise ValueError("At least one aspect ratio is required")
        return self