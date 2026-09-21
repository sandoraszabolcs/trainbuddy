"""Google-encoded polyline -> PostGIS geometry helpers.

Strava gives a `summary_polyline` (simplified) on the activity list endpoint.
That is plenty for home-base clustering and map circles, and it is never shown
to anyone but the owner.
"""

from itertools import groupby

import polyline as polyline_lib


# Longitude first in WKT, latitude second - the classic way to get this backwards.
def to_point_ewkt(lat: float, lng: float) -> str:
    return f"SRID=4326;POINT({lng} {lat})"


def decode_polyline(encoded: str | None) -> list[tuple[float, float]]:
    """Decode to [(lat, lng), ...]; returns [] for missing or corrupt input.

    The decoder does not raise on garbage - it happily returns coordinates like
    latitude 108191, which PostGIS then rejects mid-sync (or, worse, accepts as
    a home base on the other side of the planet). So the range check is part of
    decoding, and any out-of-range point condemns the whole polyline: a corrupt
    encoding gives no reason to trust the points that happen to look sane.
    """
    if not encoded:
        return []
    try:
        points = [(float(lat), float(lng)) for lat, lng in polyline_lib.decode(encoded)]
    except (ValueError, IndexError, TypeError):
        return []
    if any(not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0) for lat, lng in points):
        return []
    return points


def to_linestring_ewkt(points: list[tuple[float, float]]) -> str | None:
    """Build a LINESTRING, collapsing only *consecutive* duplicate points.

    Deduplicating globally would destroy the routes people actually run: an
    out-and-back revisits every point on the way home, and a loop ends where it
    started, so `set`/`dict.fromkeys` would silently keep one leg and throw the
    rest away. Repeated coordinates are legitimate geometry - only a GPS pause
    (the same fix twice in a row) is noise worth dropping.
    """
    deduped = [point for point, _ in groupby(points)]
    if len(deduped) < 2:
        return None
    coords = ", ".join(f"{lng} {lat}" for lat, lng in deduped)
    return f"SRID=4326;LINESTRING({coords})"
