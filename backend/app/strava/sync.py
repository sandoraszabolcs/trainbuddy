"""Sync a Strava athlete's own activities into our schema.

Pure mapping functions live at the top (unit-tested); the DB-touching
orchestration is at the bottom.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.geo.clustering import cluster_home_bases
from app.geo.scoring import pace_s_per_km
from app.models import Activity, Athlete, HomeBase, StravaToken
from app.strava.client import StravaClient, refresh_token, token_is_expired
from app.strava.polyline_utils import decode_polyline, to_linestring_ewkt, to_point_ewkt

logger = logging.getLogger(__name__)
settings = get_settings()

# Strava has ~40 activity types; we match on the two we can pair people up for.
_SPORT_MAP = {
    "Run": "run",
    "TrailRun": "run",
    "VirtualRun": "run",
    "Ride": "ride",
    "GravelRide": "ride",
    "MountainBikeRide": "ride",
    "VirtualRide": "ride",
}


def sport_of(strava_type: str | None) -> str | None:
    return _SPORT_MAP.get(strava_type or "")


def parse_local_start(raw: str | None) -> datetime | None:
    """`start_date_local` is naive local time - exactly what habit scoring needs."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "")).replace(tzinfo=None)
    except ValueError:
        return None


def activity_from_strava(athlete_id: int, raw: dict[str, Any]) -> Activity | None:
    """Map one Strava activity payload to a row, or None if unusable.

    Skipped: unsupported sports, indoor sessions (no GPS), and anything without a
    usable local start time - none of which can produce a meet-up match.
    """
    sport = sport_of(raw.get("type") or raw.get("sport_type"))
    if sport is None:
        return None
    start_time = parse_local_start(raw.get("start_date_local"))
    if start_time is None:
        return None

    latlng = raw.get("start_latlng") or []
    points = decode_polyline((raw.get("map") or {}).get("summary_polyline"))
    if len(latlng) != 2 and not points:
        return None  # treadmill / turbo: no location, no match
    lat, lng = (latlng[0], latlng[1]) if len(latlng) == 2 else points[0]

    return Activity(
        athlete_id=athlete_id,
        strava_activity_id=raw.get("id"),
        sport=sport,
        start_point=to_point_ewkt(lat, lng),
        route=to_linestring_ewkt(points),
        start_time_local=start_time,
        distance_m=float(raw.get("distance") or 0.0),
        moving_time_s=int(raw.get("moving_time") or 0),
    )


def profile_stats(activities: list[Activity]) -> tuple[str | None, float | None, float | None]:
    """(primary sport, median pace s/km, median distance m) from activity history."""
    if not activities:
        return None, None, None

    counts: dict[str, int] = {}
    for a in activities:
        counts[a.sport] = counts.get(a.sport, 0) + 1
    primary = max(counts, key=lambda s: counts[s])

    in_sport = [a for a in activities if a.sport == primary]
    paces = sorted(
        p for a in in_sport if (p := pace_s_per_km(a.distance_m, a.moving_time_s)) is not None
    )
    distances = sorted(a.distance_m for a in in_sport if a.distance_m > 0)
    median = lambda xs: xs[len(xs) // 2] if xs else None  # noqa: E731
    return primary, median(paces), median(distances)


async def ensure_fresh_token(session: AsyncSession, token: StravaToken) -> StravaToken:
    if not token_is_expired(token.expires_at):
        return token
    logger.info("refreshing strava token for athlete %s", token.athlete_id)
    payload = await refresh_token(token.refresh_token)
    token.access_token = payload["access_token"]
    token.refresh_token = payload["refresh_token"]
    token.expires_at = datetime.fromtimestamp(payload["expires_at"], tz=UTC)
    await session.commit()
    return token


async def sync_activities(session: AsyncSession, athlete: Athlete, max_pages: int = 5) -> int:
    """Pull activities, replace this athlete's rows, then refresh derived profile data."""
    token = await session.get(StravaToken, athlete.id)
    if token is None:
        raise RuntimeError(f"athlete {athlete.id} has no stored Strava token")
    token = await ensure_fresh_token(session, token)

    raw_activities = await StravaClient(token.access_token).activities(max_pages=max_pages)
    rows = [a for raw in raw_activities if (a := activity_from_strava(athlete.id, raw))]

    await session.execute(delete(Activity).where(Activity.athlete_id == athlete.id))
    session.add_all(rows)
    await session.flush()
    await refresh_derived_profile(session, athlete)
    await session.commit()
    logger.info("synced %d activities for athlete %s", len(rows), athlete.id)
    return len(rows)


async def refresh_derived_profile(session: AsyncSession, athlete: Athlete) -> None:
    """Recompute home bases and pace/distance bands from whatever activities exist.

    Shared by the real sync and the seeder, so seeded athletes are built by the
    same code that builds the real one.
    """
    result = await session.execute(select(Activity).where(Activity.athlete_id == athlete.id))
    activities = list(result.scalars())

    primary, pace, distance = profile_stats(activities)
    if primary:
        athlete.primary_sport = primary
    athlete.pace_s_per_km = pace
    athlete.typical_distance_m = distance

    # One query for every start point: PostGIS returns lat/lng, clustering does the rest.
    coords = await session.execute(
        select(
            func.ST_Y(func.ST_AsText(Activity.start_point).cast(Geometry)),
            func.ST_X(func.ST_AsText(Activity.start_point).cast(Geometry)),
        ).where(Activity.athlete_id == athlete.id, Activity.start_point.isnot(None))
    )
    points = [(float(lat), float(lng)) for lat, lng in coords.all()]

    await session.execute(delete(HomeBase).where(HomeBase.athlete_id == athlete.id))
    for cluster in cluster_home_bases(
        points,
        eps_km=settings.cluster_eps_km,
        min_activities=settings.cluster_min_activities,
        max_clusters=settings.max_home_bases,
    ):
        session.add(
            HomeBase(
                athlete_id=athlete.id,
                point=to_point_ewkt(cluster.lat, cluster.lng),
                activity_count=cluster.activity_count,
                weight=cluster.weight,
            )
        )
    await session.flush()
