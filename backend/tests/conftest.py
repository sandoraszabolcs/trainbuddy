"""Test fixtures.

The geo, scoring and polyline tests are pure and need nothing at all. The
matching tests need real PostGIS (ST_DWithin, DISTINCT ON), so they run against
a live database and are marked `integration`. They roll back after each test, so
they can point at the compose database without disturbing seeded demo data.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Activity, Athlete, Base, HomeBase
from app.strava.polyline_utils import to_point_ewkt

# Our own image, because no public one ships PostGIS *and* pgvector.
# `docker compose build db` produces it; CI builds it before running tests.
DB_IMAGE = os.getenv("TEST_DB_IMAGE", "trainbuddy-db:latest")

# An explicit URL bypasses the container (useful in CI with a service container).
# Never defaults to DATABASE_URL: the dev database holds seeded demo athletes,
# and these tests assert on the whole result set.
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def database_url() -> AsyncIterator[str]:
    if TEST_DATABASE_URL:
        yield TEST_DATABASE_URL
        return
    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:  # pragma: no cover - older testcontainers layout
        try:
            from testcontainers.postgres import PostgresContainer
        except ImportError:
            pytest.skip("testcontainers not installed; set TEST_DATABASE_URL instead")

    try:
        with PostgresContainer(DB_IMAGE, driver="psycopg") as container:
            yield container.get_connection_url()
    except Exception as exc:  # noqa: BLE001 - no docker is a skip, not a failure
        pytest.skip(f"cannot start {DB_IMAGE}: {exc.__class__.__name__}: {exc}")


@pytest_asyncio.fixture(scope="session")
async def engine(database_url):
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        # Compose runs db/init.sql for these; a bare container needs them here.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    """A session whose work is always rolled back, so tests never leak rows."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        maker = async_sessionmaker(bind=connection, expire_on_commit=False)
        async with maker() as session:
            yield session
        await transaction.rollback()


@pytest.fixture
def make_athlete():
    """Build an athlete with explicit home bases and activity times.

    Everything the matcher reads is set directly, so a test states exactly the
    situation it is about instead of depending on the seeder's randomness.
    """

    async def _make(
        session: AsyncSession,
        *,
        name: str,
        bases: list[tuple[float, float]],
        sex: str = "F",
        sport: str = "run",
        pace_s_per_km: float | None = 300.0,
        typical_distance_m: float | None = 10_000.0,
        start_times: list[datetime] | None = None,
    ) -> Athlete:
        athlete = Athlete(
            display_name=name,
            sex=sex,
            primary_sport=sport,
            pace_s_per_km=pace_s_per_km,
            typical_distance_m=typical_distance_m,
            is_seeded=True,
            created_at=datetime.now(UTC),
        )
        session.add(athlete)
        await session.flush()

        for lat, lng in bases:
            session.add(
                HomeBase(
                    athlete_id=athlete.id,
                    point=to_point_ewkt(lat, lng),
                    activity_count=10,
                    weight=1.0 / len(bases),
                )
            )
        for start in start_times or []:
            session.add(
                Activity(
                    athlete_id=athlete.id,
                    sport=sport,
                    start_point=to_point_ewkt(*bases[0]),
                    route=None,
                    start_time_local=start,
                    distance_m=typical_distance_m or 10_000.0,
                    moving_time_s=3000,
                )
            )
        await session.flush()
        return athlete

    return _make
