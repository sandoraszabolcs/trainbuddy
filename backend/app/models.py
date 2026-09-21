"""Database schema.

Seeded athletes and the real (Strava-synced) athlete share every table: the only
difference is `athlete.is_seeded`, so matching code never has two paths.
"""

from datetime import datetime

from geoalchemy2 import Geography
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 384  # BAAI/bge-small-en-v1.5


class Base(DeclarativeBase):
    pass


class Athlete(Base):
    __tablename__ = "athlete"

    id: Mapped[int] = mapped_column(primary_key=True)
    strava_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    sex: Mapped[str | None] = mapped_column(String(1))  # Strava exposes 'M' / 'F' only
    primary_sport: Mapped[str] = mapped_column(String(20), default="run")  # run | ride
    # derived from activity history, refreshed after each sync/seed
    pace_s_per_km: Mapped[float | None] = mapped_column(Float)
    typical_distance_m: Mapped[float | None] = mapped_column(Float)
    persona_text: Mapped[str | None] = mapped_column(Text)
    self_declared_age: Mapped[int | None] = mapped_column(Integer)
    is_seeded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    home_bases: Mapped[list["HomeBase"]] = relationship(
        back_populates="athlete", cascade="all, delete-orphan"
    )
    activities: Mapped[list["Activity"]] = relationship(
        back_populates="athlete", cascade="all, delete-orphan"
    )


class StravaToken(Base):
    """Server-side token storage; never leaves the backend."""

    __tablename__ = "strava_token"

    athlete_id: Mapped[int] = mapped_column(ForeignKey("athlete.id", ondelete="CASCADE"), primary_key=True)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scope: Mapped[str] = mapped_column(Text, default="")


class HomeBase(Base):
    """A cluster of activity start points: 'where this athlete usually trains'."""

    __tablename__ = "home_base"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(
        ForeignKey("athlete.id", ondelete="CASCADE"), index=True
    )
    point: Mapped[str] = mapped_column(Geography("POINT", srid=4326))
    activity_count: Mapped[int] = mapped_column(Integer, default=0)
    weight: Mapped[float] = mapped_column(Float, default=1.0)  # share of this athlete's activities

    # GeoAlchemy2 creates the GiST index on `point` automatically (idx_home_base_point).
    athlete: Mapped[Athlete] = relationship(back_populates="home_bases")


class Activity(Base):
    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(
        ForeignKey("athlete.id", ondelete="CASCADE"), index=True
    )
    strava_activity_id: Mapped[int | None] = mapped_column(BigInteger)
    sport: Mapped[str] = mapped_column(String(20))
    start_point: Mapped[str | None] = mapped_column(Geography("POINT", srid=4326))
    route: Mapped[str | None] = mapped_column(Geography("LINESTRING", srid=4326))
    start_time_local: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    distance_m: Mapped[float] = mapped_column(Float)
    moving_time_s: Mapped[int] = mapped_column(Integer)

    athlete: Mapped[Athlete] = relationship(back_populates="activities")

    __table_args__ = (
        UniqueConstraint("athlete_id", "strava_activity_id", name="uq_activity_strava"),
    )


class AthleteEmbedding(Base):
    """Persona card embedding, used for semantic ('chatty hill runner') matching."""

    __tablename__ = "athlete_embedding"

    athlete_id: Mapped[int] = mapped_column(
        ForeignKey("athlete.id", ondelete="CASCADE"), primary_key=True
    )
    card_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))


class KbChunk(Base):
    """Training knowledge base: real documents the agent cites. This is the RAG corpus."""

    __tablename__ = "kb_chunk"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))


class Message(Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("athlete.id", ondelete="CASCADE"), index=True)
    recipient_id: Mapped[int] = mapped_column(
        ForeignKey("athlete.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MatchRequest(Base):
    """Audit row per agent run: what was asked, what the agent relaxed, what it returned."""

    __tablename__ = "match_request"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athlete.id", ondelete="CASCADE"))
    query_text: Mapped[str | None] = mapped_column(Text)
    filters_json: Mapped[str] = mapped_column(Text)
    relaxations_json: Mapped[str] = mapped_column(Text, default="[]")
    result_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
