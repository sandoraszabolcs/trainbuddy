"""Candidate query behaviour, against real PostGIS.

These cover the parts that cannot be tested without a database: the ST_DWithin
radius gate, one-row-per-athlete collapsing, and the NULL handling of the pace
filter.
"""

from datetime import datetime

import pytest

from app.matching import find_candidates
from app.schemas import MatchFilters

pytestmark = pytest.mark.integration

CENTRE = (47.4979, 19.0402)  # Budapest


def offset(km_north: float, km_east: float = 0.0) -> tuple[float, float]:
    """A point roughly `km_north`/`km_east` from CENTRE - good enough for radius tests."""
    import math

    return (
        CENTRE[0] + km_north / 111.0,
        CENTRE[1] + km_east / (111.0 * math.cos(math.radians(CENTRE[0]))),
    )


def filters(**overrides) -> MatchFilters:
    base = {"lat": CENTRE[0], "lng": CENTRE[1], "radius_km": 20.0, "sport": "run", "limit": 10}
    return MatchFilters(**{**base, **overrides})


SATURDAYS = [datetime(2026, 9, d, 8) for d in (5, 12, 19, 26)]


class TestOneRowPerAthlete:
    async def test_multi_base_athlete_appears_exactly_once(self, session, make_athlete):
        """Regression: three bases in radius produced three identical results."""
        await make_athlete(
            session,
            name="Three Bases",
            bases=[offset(2), offset(5), offset(8)],
            start_times=SATURDAYS,
        )
        results = await find_candidates(session, filters())
        assert [r.display_name for r in results] == ["Three Bases"]

    async def test_duplicates_do_not_consume_the_limit(self, session, make_athlete):
        """Regression: duplicate rows crowded out other people's results."""
        for i in range(3):
            await make_athlete(
                session,
                name=f"Multi {i}",
                bases=[offset(2 + i), offset(6 + i), offset(10 + i)],
                start_times=SATURDAYS,
            )
        results = await find_candidates(session, filters(limit=3))
        assert len(results) == 3
        assert len({r.athlete_id for r in results}) == 3

    async def test_reported_base_is_the_nearest_one(self, session, make_athlete):
        """The card must show the base that made them eligible, not an arbitrary one."""
        await make_athlete(
            session, name="Near And Far", bases=[offset(18), offset(3)], start_times=SATURDAYS
        )
        (result,) = await find_candidates(session, filters())
        assert result.distance_km == pytest.approx(3.0, abs=0.6)


class TestRadiusGate:
    async def test_athlete_outside_the_radius_is_excluded(self, session, make_athlete):
        await make_athlete(session, name="Too Far", bases=[offset(35)], start_times=SATURDAYS)
        assert await find_candidates(session, filters(radius_km=20)) == []

    async def test_second_base_inside_the_radius_qualifies_the_athlete(
        self, session, make_athlete
    ):
        """The whole point of multiple home bases: any one of them can match."""
        await make_athlete(
            session, name="Far Home Near Office", bases=[offset(40), offset(4)],
            start_times=SATURDAYS,
        )
        results = await find_candidates(session, filters(radius_km=10))
        assert [r.display_name for r in results] == ["Far Home Near Office"]


class TestPaceFilter:
    async def test_unknown_pace_is_not_excluded(self, session, make_athlete):
        """Regression: `between` is NULL for a NULL pace, which hid these athletes.

        scoring.pace_score() documents an unknown pace as neutral, never a
        penalty; the SQL gate must agree with it.
        """
        await make_athlete(
            session, name="No Pace Yet", bases=[offset(3)],
            pace_s_per_km=None, start_times=SATURDAYS,
        )
        results = await find_candidates(session, filters(pace_s_per_km=300, pace_tolerance_s=30))
        assert [r.display_name for r in results] == ["No Pace Yet"]

    async def test_pace_outside_tolerance_is_excluded(self, session, make_athlete):
        await make_athlete(
            session, name="Much Faster", bases=[offset(3)],
            pace_s_per_km=200.0, start_times=SATURDAYS,
        )
        assert await find_candidates(session, filters(pace_s_per_km=300, pace_tolerance_s=30)) == []

    async def test_pace_inside_tolerance_is_kept(self, session, make_athlete):
        await make_athlete(
            session, name="Similar Pace", bases=[offset(3)],
            pace_s_per_km=310.0, start_times=SATURDAYS,
        )
        results = await find_candidates(session, filters(pace_s_per_km=300, pace_tolerance_s=30))
        assert [r.display_name for r in results] == ["Similar Pace"]


class TestFilters:
    async def test_sex_filter_applies(self, session, make_athlete):
        await make_athlete(session, name="Woman", bases=[offset(3)], sex="F",
                           start_times=SATURDAYS)
        await make_athlete(session, name="Man", bases=[offset(3)], sex="M", start_times=SATURDAYS)
        results = await find_candidates(session, filters(sex="F"))
        assert [r.display_name for r in results] == ["Woman"]

    async def test_sport_filter_applies(self, session, make_athlete):
        await make_athlete(session, name="Runner", bases=[offset(3)], sport="run",
                           start_times=SATURDAYS)
        await make_athlete(session, name="Cyclist", bases=[offset(3)], sport="ride",
                           start_times=SATURDAYS)
        results = await find_candidates(session, filters(sport="ride"))
        assert [r.display_name for r in results] == ["Cyclist"]

    async def test_excluded_athlete_is_never_their_own_match(self, session, make_athlete):
        me = await make_athlete(session, name="Me", bases=[offset(1)], start_times=SATURDAYS)
        await make_athlete(session, name="Someone Else", bases=[offset(3)],
                           start_times=SATURDAYS)
        results = await find_candidates(session, filters(), exclude_athlete_id=me.id)
        assert [r.display_name for r in results] == ["Someone Else"]


class TestDisplayPolicy:
    async def test_card_exposes_no_precise_location(self, session, make_athlete):
        """D5b: a coarse area circle only - no routes, coordinates or activity list."""
        await make_athlete(session, name="Coarse", bases=[offset(3)], start_times=SATURDAYS)
        (result,) = await find_candidates(session, filters())

        assert result.area.radius_km >= 1.0
        # Coordinates are rounded to 2 dp (~hundreds of metres), not raw.
        assert result.area.lat == round(result.area.lat, 2)
        assert result.area.lng == round(result.area.lng, 2)

        payload = result.model_dump()
        for leaked in ("route", "polyline", "activities", "start_point"):
            assert leaked not in payload

    async def test_ranking_is_ordered_by_score(self, session, make_athlete):
        await make_athlete(session, name="Saturday Regular", bases=[offset(2)],
                           start_times=SATURDAYS)
        await make_athlete(session, name="Never Saturdays", bases=[offset(2)],
                           start_times=[datetime(2026, 9, d, 19) for d in (8, 9, 10)])
        results = await find_candidates(session, filters(target_date="2026-09-19", target_hour=8))
        assert [r.display_name for r in results] == ["Saturday Regular", "Never Saturdays"]
        assert results[0].score > results[1].score
