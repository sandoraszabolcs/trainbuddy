"""Build the route pool that seeded athletes' activities are derived from.

Primary source: the real user's own synced activity polylines. They are genuinely
local (they are where the user actually trains) and need no extra Strava call -
which matters because `segments/explore` was restricted to Extended Access Tier
developers on 2026-09-01.

`--synthetic` is a development fallback so the rest of the stack can be built and
tested before anyone has connected a Strava account. It is never used for a demo.

Usage:
    python -m app.seed.route_pool                       # from synced activities
    python -m app.seed.route_pool --synthetic 47.5,19.05  # dev only
"""

import argparse
import asyncio
import json
import math
from pathlib import Path
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import func, select

from app.db import SessionLocal
from app.geo.clustering import haversine_km
from app.models import Activity

FIXTURE = Path(__file__).parent / "fixtures" / "route_pool.json"


def route_length_km(points: list[tuple[float, float]]) -> float:
    return sum(haversine_km(a, b) for a, b in zip(points, points[1:], strict=False))


async def pool_from_db() -> dict[str, Any]:
    async with SessionLocal() as session:
        rows = await session.execute(
            select(
                Activity.sport,
                func.ST_AsGeoJSON(func.ST_AsText(Activity.route).cast(Geometry)),
            ).where(Activity.route.isnot(None))
        )
        routes = []
        for sport, geojson in rows.all():
            coords = json.loads(geojson)["coordinates"]  # [[lng, lat], ...]
            points = [(float(lat), float(lng)) for lng, lat in coords]
            if len(points) < 5:
                continue
            routes.append({"sport": sport, "points": points, "length_km": route_length_km(points)})
    return _finalise(routes)


def synthetic_pool(center: tuple[float, float], count: int = 12) -> dict[str, Any]:
    """Dev-only: rough loops around a point. Obviously synthetic on a map."""
    routes = []
    for i in range(count):
        length_km = 4.0 + (i % 6) * 2.5
        radius_deg = (length_km / (2 * math.pi)) / 111.0
        steps = 40
        points = [
            (
                center[0] + radius_deg * math.sin(2 * math.pi * s / steps),
                center[1] + radius_deg * math.cos(2 * math.pi * s / steps) / math.cos(
                    math.radians(center[0])
                ),
            )
            for s in range(steps + 1)
        ]
        routes.append(
            {
                "sport": "run" if i % 2 == 0 else "ride",
                "points": points,
                "length_km": route_length_km(points),
            }
        )
    return _finalise(routes)


def _finalise(routes: list[dict[str, Any]]) -> dict[str, Any]:
    if not routes:
        raise SystemExit(
            "No routes found. Connect Strava and sync first, or use "
            "--synthetic <lat>,<lng> for local development."
        )
    lats = [p[0] for r in routes for p in r["points"]]
    lngs = [p[1] for r in routes for p in r["points"]]
    return {
        "center": [sum(lats) / len(lats), sum(lngs) / len(lngs)],
        "route_count": len(routes),
        "routes": routes,
    }


def load_pool() -> dict[str, Any]:
    if not FIXTURE.exists():
        raise SystemExit(f"{FIXTURE} missing - run `python -m app.seed.route_pool` first.")
    return json.loads(FIXTURE.read_text())


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", metavar="LAT,LNG", help="dev fallback: loops around a point")
    args = parser.parse_args()

    if args.synthetic:
        lat, lng = (float(v) for v in args.synthetic.split(","))
        pool = synthetic_pool((lat, lng))
    else:
        pool = await pool_from_db()

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(pool))
    print(
        f"wrote {FIXTURE} - {pool['route_count']} routes, "
        f"center {pool['center'][0]:.4f},{pool['center'][1]:.4f}"
    )


if __name__ == "__main__":
    asyncio.run(main())
