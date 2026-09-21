"""Match scoring: pure functions over already-fetched data, so they unit-test fast.

The radius gate decides *eligibility* (done in SQL with ST_DWithin); these
functions decide *ranking* among the eligible.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

# Weights sum to 1.0. Tuned so "trains at the same time" and "trains at the same
# speed" dominate: being 3 km closer matters less than being unable to keep up.
W_HABIT = 0.35
W_PACE = 0.30
W_DISTANCE = 0.20
W_PROXIMITY = 0.15


@dataclass(frozen=True)
class ScoreBreakdown:
    habit: float
    pace: float
    distance: float
    proximity: float

    @property
    def total(self) -> float:
        return (
            W_HABIT * self.habit
            + W_PACE * self.pace
            + W_DISTANCE * self.distance
            + W_PROXIMITY * self.proximity
        )


def habit_score(
    start_times: Sequence[datetime],
    target_weekday: int,
    target_hour: int,
    hour_window: int = 3,
) -> float:
    """How habitually does this athlete train on that weekday, around that hour?

    Returns the share of their activities that fall on the target weekday within
    +/- `hour_window` hours, scaled so that 'a third of my training is Saturday
    morning' already scores 1.0 - habits are diffuse, and demanding 100% would
    make every score near zero.
    """
    if not start_times:
        return 0.0
    hits = sum(
        1
        for t in start_times
        if t.weekday() == target_weekday and abs(t.hour - target_hour) <= hour_window
    )
    return min(1.0, (hits / len(start_times)) / 0.33)


def pace_score(mine_s_per_km: float | None, theirs_s_per_km: float | None) -> float:
    """1.0 at identical pace, 0.0 once they are 60 s/km apart (~a different session)."""
    if not mine_s_per_km or not theirs_s_per_km:
        return 0.5  # unknown: neutral, never a penalty
    return max(0.0, 1.0 - abs(mine_s_per_km - theirs_s_per_km) / 60.0)


def distance_score(mine_m: float | None, theirs_m: float | None) -> float:
    """Ratio-based: 10 km vs 12 km is close; 10 km vs 30 km is not."""
    if not mine_m or not theirs_m:
        return 0.5
    ratio = min(mine_m, theirs_m) / max(mine_m, theirs_m)
    return max(0.0, (ratio - 0.5) * 2.0)  # 1.0 at equal, 0.0 at half/double


def proximity_score(distance_km: float, radius_km: float) -> float:
    """Linear inside the radius; the gate itself already excluded anything beyond."""
    if radius_km <= 0:
        return 0.0
    return max(0.0, 1.0 - distance_km / radius_km)


def score_candidate(
    *,
    start_times: Sequence[datetime],
    target_weekday: int,
    target_hour: int,
    my_pace: float | None,
    their_pace: float | None,
    my_distance: float | None,
    their_distance: float | None,
    distance_km: float,
    radius_km: float,
) -> ScoreBreakdown:
    return ScoreBreakdown(
        habit=habit_score(start_times, target_weekday, target_hour),
        pace=pace_score(my_pace, their_pace),
        distance=distance_score(my_distance, their_distance),
        proximity=proximity_score(distance_km, radius_km),
    )


def pace_s_per_km(distance_m: float, moving_time_s: float) -> float | None:
    if distance_m <= 0 or moving_time_s <= 0:
        return None
    return moving_time_s / (distance_m / 1000.0)
