"""API request/response models.

The response types are where the display policy lives: a match card carries
derived, coarse fields only - never another athlete's routes, exact coordinates
or activity list.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Sport = Literal["run", "ride"]
Sex = Literal["F", "M"]


class MatchFilters(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="search centre latitude")
    lng: float = Field(..., ge=-180, le=180, description="search centre longitude")
    radius_km: float = Field(20.0, gt=0, le=50)
    sport: Sport = "run"
    sex: Sex | None = None
    target_date: date | None = Field(None, description="day we want to train together")
    target_hour: int = Field(8, ge=0, le=23)
    pace_s_per_km: float | None = Field(None, gt=0, description="my pace; None = derive from history")
    pace_tolerance_s: float = Field(45.0, ge=0, le=300)
    distance_m: float | None = Field(None, gt=0)
    limit: int = Field(10, ge=1, le=50)

    @property
    def weekday(self) -> int:
        return self.target_date.weekday() if self.target_date else 5  # default Saturday


class AreaSummary(BaseModel):
    """Deliberately coarse: a circle, never a point. See D5b in the plan."""

    lat: float
    lng: float
    radius_km: float = 1.5


class MatchResult(BaseModel):
    athlete_id: int
    display_name: str
    sex: Sex | None
    sport: Sport
    pace_s_per_km: float | None
    typical_distance_m: float | None
    self_declared_age: int | None
    persona_text: str | None
    area: AreaSummary
    distance_km: float
    habitual_days: list[int]
    score: float
    score_breakdown: dict[str, float]
    reason: str | None = None
    opener: str | None = None


class MatchResponse(BaseModel):
    filters_applied: MatchFilters
    relaxations: list[str] = []
    results: list[MatchResult]
