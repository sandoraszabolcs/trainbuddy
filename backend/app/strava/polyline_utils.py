"""Google-encoded polyline -> PostGIS geometry helpers.

Strava gives a `summary_polyline` (simplified) on the activity list endpoint.
That is plenty for home-base clustering and map circles, and it is never shown
to anyone but the owner.
"""

import polyline as polyline_lib

# Longitude first in WKT, latitude second - the classic way to get this backwards.
def to_point_ewkt(lat: float, lng: float) -> str:
    return f"SRID=4326;POINT({lng} {lat})"


def decode_polyline(encoded: str | None) -> list[tuple[float, float]]:
    """Decode to [(lat, lng), ...]; returns [] for missing or corrupt input."""
    if not encoded:
        return []
    try:
        return [(float(lat), float(lng)) for lat, lng in polyline_lib.decode(encoded)]
    except (ValueError, IndexError, TypeError):
        return []


def to_linestring_ewkt(points: list[tuple[float, float]]) -> str | None:
    """A LINESTRING needs >= 2 distinct points; anything less is not a route."""
    distinct = list(dict.fromkeys(points))
    if len(distinct) < 2:
        return None
    coords = ", ".join(f"{lng} {lat}" for lat, lng in distinct)
    return f"SRID=4326;LINESTRING({coords})"
