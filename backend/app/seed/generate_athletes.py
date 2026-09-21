"""Seed the matching pool.

Strava only ever exposes the token owner's own data, so the other athletes in
this app are rows we create. They go through the same tables and the same
derived-profile code as the real synced user - `athlete.is_seeded` is the only
difference, and matching never branches on it.

Usage:
    python -m app.seed.generate_athletes --count 100 [--reset]
"""

import argparse
import asyncio
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db import SessionLocal
from app.geo.clustering import haversine_km
from app.models import Activity, Athlete, HomeBase
from app.seed.personas import ARCHETYPES, Archetype, fallback_card, random_name
from app.seed.route_pool import load_pool
from app.strava.polyline_utils import to_linestring_ewkt, to_point_ewkt
from app.strava.sync import refresh_derived_profile

settings = get_settings()

KM_PER_DEG_LAT = 111.0


def offset_point(
    center: tuple[float, float], bearing_deg: float, distance_km: float
) -> tuple[float, float]:
    import math

    rad = math.radians(bearing_deg)
    dlat = (distance_km * math.cos(rad)) / KM_PER_DEG_LAT
    dlng = (distance_km * math.sin(rad)) / (KM_PER_DEG_LAT * math.cos(math.radians(center[0])))
    return center[0] + dlat, center[1] + dlng


def translate_route(
    points: list[tuple[float, float]], target_start: tuple[float, float]
) -> list[tuple[float, float]]:
    """Move a real route so it starts at this athlete's home base."""
    dlat = target_start[0] - points[0][0]
    dlng = target_start[1] - points[0][1]
    return [(lat + dlat, lng + dlng) for lat, lng in points]


def pick_home_bases(
    center: tuple[float, float], rng: random.Random, spread_km: float
) -> list[tuple[float, float]]:
    """1-3 areas per athlete, scattered across the demo region."""
    count = rng.choices([1, 2, 3], weights=[0.6, 0.3, 0.1])[0]
    return [
        offset_point(center, rng.uniform(0, 360), rng.uniform(0.5, spread_km)) for _ in range(count)
    ]


def build_activities(
    athlete_id: int,
    archetype: Archetype,
    bases: list[tuple[float, float]],
    pool_routes: list[dict],
    pace_s_per_km: float,
    rng: random.Random,
    weeks: int = 16,
) -> list[Activity]:
    """Generate a plausible training history: same weekday/hour habits week after week."""
    sport_routes = [r for r in pool_routes if r["sport"] == archetype.sport] or pool_routes
    activities: list[Activity] = []
    now = datetime.now()

    for week in range(weeks):
        for weekday in archetype.preferred_days:
            if rng.random() > 0.75:  # not every planned session happens
                continue
            base = rng.choice(bases)
            route = rng.choice(sport_routes)
            points = translate_route(
                [(lat, lng) for lat, lng in route["points"]],
                offset_point(base, rng.uniform(0, 360), rng.uniform(0.0, 0.4)),
            )
            distance_m = max(1000.0, route["length_km"] * 1000 * rng.uniform(0.85, 1.15))
            pace = pace_s_per_km * rng.uniform(0.95, 1.08)
            start = now - timedelta(weeks=weeks - week)
            start = start - timedelta(days=(start.weekday() - weekday) % 7)
            start = start.replace(
                hour=rng.choice(archetype.preferred_hours),
                minute=rng.choice([0, 10, 15, 30, 45]),
                second=0,
                microsecond=0,
            )
            activities.append(
                Activity(
                    athlete_id=athlete_id,
                    strava_activity_id=None,
                    sport=archetype.sport,
                    start_point=to_point_ewkt(*points[0]),
                    route=to_linestring_ewkt(points),
                    start_time_local=start,
                    distance_m=distance_m,
                    moving_time_s=int(distance_m / 1000 * pace),
                )
            )
    return activities


async def seed(count: int, reset: bool, seed_value: int, spread_km: float) -> None:
    rng = random.Random(seed_value)
    pool = load_pool()
    center = (pool["center"][0], pool["center"][1])

    async with SessionLocal() as session:
        if reset:
            existing = (
                await session.execute(select(Athlete.id).where(Athlete.is_seeded.is_(True)))
            ).scalars().all()
            if existing:
                await session.execute(delete(Athlete).where(Athlete.id.in_(existing)))
                await session.commit()
                print(f"removed {len(existing)} previously seeded athletes")

        for _ in range(count):
            archetype = rng.choice(ARCHETYPES)
            sex = rng.choice(["F", "M"])
            name = random_name(sex, rng)
            pace = rng.uniform(*archetype.pace_range)
            distance = rng.uniform(*archetype.distance_range)

            athlete = Athlete(
                display_name=name,
                sex=sex,
                primary_sport=archetype.sport,
                self_declared_age=rng.choice([None, rng.randint(22, 58)]),
                persona_text=fallback_card(name, archetype, pace, distance),
                is_seeded=True,
                created_at=datetime.now(UTC),
            )
            session.add(athlete)
            await session.flush()

            bases = pick_home_bases(center, rng, spread_km)
            session.add_all(
                build_activities(athlete.id, archetype, bases, pool["routes"], pace, rng)
            )
            await session.flush()
            # same derived-profile code the real Strava sync uses
            await refresh_derived_profile(session, athlete)

        await session.commit()

        seeded = await session.scalar(
            select(func.count(Athlete.id)).where(Athlete.is_seeded.is_(True))
        )
        bases = await session.scalar(select(func.count(HomeBase.id)))
        activities = await session.scalar(select(func.count(Activity.id)))
        print(f"seeded athletes: {seeded}, home bases: {bases}, activities: {activities}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--reset", action="store_true", help="delete existing seeded athletes first")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed, for reproducible demos")
    parser.add_argument(
        "--spread-km", type=float, default=25.0, help="how far home bases scatter from the centre"
    )
    args = parser.parse_args()
    await seed(args.count, args.reset, args.seed, args.spread_km)


if __name__ == "__main__":
    asyncio.run(main())
