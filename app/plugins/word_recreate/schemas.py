"""The word recreation plugin's public inputs, independent of the native engine."""
from typing import Literal

from pydantic import BaseModel, Field

from ...schemas import Options, PlanInput, ProjectInput


class WordOptions(Options):
    engine: Literal["hypit"] = "hypit"
    caption_style: Literal["highlight", "plain"] = "highlight"


class WordProjectInput(ProjectInput):
    options: WordOptions = Field(default_factory=WordOptions)


class WordSettingsInput(BaseModel):
    model_config = {"extra": "forbid"}
    enabled: bool = Field(strict=True)


class WordSettings(WordSettingsInput):
    enabled: bool = Field(default=False, strict=True)


class WordPlanInput(PlanInput):
    pass
