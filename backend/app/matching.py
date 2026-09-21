"""Candidate search + ranking.

Eligibility is decided in SQL (ST_DWithin against home bases, index-backed);
ranking is decided by the pure functions in app.geo.scoring.
"""

import logging
from collections import defaultdict

from geoalchemy2 import Geography, Geometry
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.scoring import score_candidate
from app.models import Activity, Athlete, HomeBase
from app.schemas import AreaSummary, MatchFilters, MatchResult

logger = logging.getLogger(__name__)

# Coarsening applied to every area we show: ~1 km of rounding, plus a stated radius.
AREA_PRECISION = 2
AREA_RADIUS_KM = 1.5


async def find_candidates(
    session: AsyncSession, filters: MatchFilters, *, exclude_athlete_id: int | None = None
) -> list[MatchResult]:
    """Athletes with a home base inside the radius, ranked by training compatibility."""
    centre = func.ST_SetSRID(func.ST_MakePoint(filters.lng, filters.lat), 4326).cast(
        Geography(geometry_type="POINT", srid=4326)
    )
    distance_m = func.ST_Distance(HomeBase.point, centre)

    # Pick each athlete's *nearest* eligible home base, one row per athlete.
    #
    # An athlete deliberately has up to 3 home bases (see D3), so a plain
    # WHERE ST_DWithin join yields one row per matching base. Grouping by
    # (athlete, base) does not collapse them either - it just makes the group key
    # the pair. DISTINCT ON (athlete.id) with ORDER BY athlete.id, distance keeps
    # the closest base and discards the rest.
    nearest_base = (
        select(
            Athlete.id.label("athlete_id"),
            distance_m.label("distance_m"),
            func.ST_Y(func.ST_AsText(HomeBase.point).cast(Geometry)).label("base_lat"),
            func.ST_X(func.ST_AsText(HomeBase.point).cast(Geometry)).label("base_lng"),
        )
        .join(HomeBase, HomeBase.athlete_id == Athlete.id)
        .where(func.ST_DWithin(HomeBase.point, centre, filters.radius_km * 1000))
        .where(Athlete.primary_sport == filters.sport)
        .distinct(Athlete.id)
        .order_by(Athlete.id, distance_m)
    )
    if filters.sex:
        nearest_base = nearest_base.where(Athlete.sex == filters.sex)
    if exclude_athlete_id is not None:
        nearest_base = nearest_base.where(Athlete.id != exclude_athlete_id)
    if filters.pace_s_per_km:
        low = filters.pace_s_per_km - filters.pace_tolerance_s
        high = filters.pace_s_per_km + filters.pace_tolerance_s
        # An unknown pace must not exclude anyone: pace_score() treats None as
        # neutral, and `between` is NULL (so falsy) for a NULL column, which
        # would quietly hide every athlete whose history yields no pace.
        nearest_base = nearest_base.where(
            or_(Athlete.pace_s_per_km.is_(None), Athlete.pace_s_per_km.between(low, high))
        )

    base = nearest_base.subquery()
    stmt = (
        select(Athlete, base.c.distance_m, base.c.base_lat, base.c.base_lng)
        .join(base, base.c.athlete_id == Athlete.id)
        .order_by(base.c.distance_m)
        .limit(filters.limit * 5)  # over-fetch: ranking may reorder substantially
    )

    rows = (await session.execute(stmt)).all()
    if not rows:
        return []

    habits = await _habit_history(session, [athlete.id for athlete, *_ in rows])

    results: list[MatchResult] = []
    for athlete, distance_m_value, base_lat, base_lng in rows:
        start_times = habits.get(athlete.id, [])
        breakdown = score_candidate(
            start_times=start_times,
            target_weekday=filters.weekday,
            target_hour=filters.target_hour,
            my_pace=filters.pace_s_per_km,
            their_pace=athlete.pace_s_per_km,
            my_distance=filters.distance_m,
            their_distance=athlete.typical_distance_m,
            distance_km=float(distance_m_value) / 1000.0,
            radius_km=filters.radius_km,
        )
        results.append(
            MatchResult(
                athlete_id=athlete.id,
                display_name=athlete.display_name,
                sex=athlete.sex,
                sport=athlete.primary_sport,
                pace_s_per_km=athlete.pace_s_per_km,
                typical_distance_m=athlete.typical_distance_m,
                self_declared_age=athlete.self_declared_age,
                persona_text=athlete.persona_text,
                area=AreaSummary(
                    lat=round(float(base_lat), AREA_PRECISION),
                    lng=round(float(base_lng), AREA_PRECISION),
                    radius_km=AREA_RADIUS_KM,
                ),
                distance_km=round(float(distance_m_value) / 1000.0, 1),
                habitual_days=_habitual_days(start_times),
                score=round(breakdown.total, 4),
                score_breakdown={
                    "habit": round(breakdown.habit, 3),
                    "pace": round(breakdown.pace, 3),
                    "distance": round(breakdown.distance, 3),
                    "proximity": round(breakdown.proximity, 3),
                },
            )
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return results[: filters.limit]


async def _habit_history(
    session: AsyncSession, athlete_ids: list[int]
) -> dict[int, list]:
    rows = await session.execute(
        select(Activity.athlete_id, Activity.start_time_local).where(
            Activity.athlete_id.in_(athlete_ids)
        )
    )
    history: dict[int, list] = defaultdict(list)
    for athlete_id, start_time in rows.all():
        history[athlete_id].append(start_time)
    return history


def _habitual_days(start_times: list) -> list[int]:
    """The weekdays this athlete trains on at least 15% of the time."""
    if not start_times:
        return []
    counts: dict[int, int] = defaultdict(int)
    for t in start_times:
        counts[t.weekday()] += 1
    threshold = max(1, int(len(start_times) * 0.15))
    return sorted(day for day, n in counts.items() if n >= threshold)
