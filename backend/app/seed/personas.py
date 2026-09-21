"""Persona archetypes for seeded athletes.

The text is what gets embedded for semantic search ("someone chatty who likes
hills"), so it has to read like a person, not like a row.
"""

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Archetype:
    key: str
    sport: str
    blurb: str
    pace_range: tuple[float, float]  # seconds per km
    distance_range: tuple[float, float]  # metres
    preferred_days: tuple[int, ...]  # 0 = Monday
    preferred_hours: tuple[int, ...]


ARCHETYPES: tuple[Archetype, ...] = (
    Archetype("early_bird_runner", "run",
              "Early riser who runs before work and likes steady conversational efforts.",
              (300, 360), (6000, 10000), (0, 1, 2, 3, 4), (6, 7)),
    Archetype("weekend_long_runner", "run",
              "Marathon-focused, lives for the Saturday long run, happy to chat the whole way.",
              (290, 340), (18000, 32000), (5, 6), (8, 9)),
    Archetype("trail_hills", "run",
              "Prefers trails and hill repeats to flat tarmac, never checks pace on climbs.",
              (330, 420), (10000, 18000), (5, 6), (7, 8, 9)),
    Archetype("evening_intervals", "run",
              "Track and tempo sessions after work, focused, likes a training partner to push.",
              (250, 300), (8000, 14000), (1, 3), (18, 19)),
    Archetype("commuter_cyclist", "ride",
              "Rides to work daily, up for easy spins and coffee stops at the weekend.",
              (130, 170), (15000, 30000), (0, 1, 2, 3, 4), (7, 17, 18)),
    Archetype("weekend_group_rider", "ride",
              "Weekend group ride regular, steady on the front, strong on rolling terrain.",
              (110, 140), (60000, 120000), (5, 6), (8, 9)),
    Archetype("gravel_explorer", "ride",
              "Gravel and forest tracks over main roads, always looking for a new loop.",
              (140, 190), (40000, 80000), (5, 6), (9, 10)),
    Archetype("casual_jogger", "run",
              "Runs three times a week to stay healthy, social pace, no training plan.",
              (360, 440), (4000, 8000), (1, 3, 6), (17, 18, 19)),
)

FIRST_NAMES_F = ["Anna", "Eszter", "Kata", "Petra", "Nora", "Zsofi", "Rita", "Dora", "Lilla", "Vera"]
FIRST_NAMES_M = ["Adam", "Bence", "Daniel", "Gergo", "Marton", "Peter", "Tamas", "Zoltan", "Akos", "Mate"]
LAST_INITIALS = list("BCDFGHKLMNPRSTVZ")


def random_name(sex: str, rng: random.Random) -> str:
    first = rng.choice(FIRST_NAMES_F if sex == "F" else FIRST_NAMES_M)
    return f"{first} {rng.choice(LAST_INITIALS)}."


def fallback_card(name: str, archetype: Archetype, pace: float, distance_m: float) -> str:
    """Used when no ANTHROPIC_API_KEY is set, so seeding works offline."""
    pace_txt = f"{int(pace // 60)}:{int(pace % 60):02d}/km"
    return (
        f"{name}. {archetype.blurb} Typical session {distance_m / 1000:.0f} km "
        f"at around {pace_txt}."
    )
