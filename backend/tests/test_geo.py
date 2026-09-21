"""Geo maths tests: no database, no network, milliseconds."""

from datetime import datetime

import pytest

from app.geo.clustering import cluster_home_bases, haversine_km
from app.geo.scoring import (
    distance_score,
    habit_score,
    pace_score,
    pace_s_per_km,
    proximity_score,
    score_candidate,
)

BUDA = (47.4979, 19.0402)
DEBRECEN = (47.5316, 21.6273)


def _scatter(center: tuple[float, float], n: int, spread_deg: float = 0.004) -> list[tuple[float, float]]:
    """n points in a tight blob around center (roughly a few hundred metres)."""
    return [(center[0] + (i % 5) * spread_deg, center[1] + (i % 3) * spread_deg) for i in range(n)]


class TestClustering:
    def test_empty_input_returns_no_bases(self):
        assert cluster_home_bases([]) == []

    def test_single_blob_becomes_one_home_base(self):
        clusters = cluster_home_bases(_scatter(BUDA, 20))
        assert len(clusters) == 1
        assert haversine_km((clusters[0].lat, clusters[0].lng), BUDA) < 1.0
        assert clusters[0].activity_count == 20
        assert clusters[0].weight == pytest.approx(1.0)

    def test_two_areas_produce_two_home_bases(self):
        """The whole reason for DBSCAN: a single centroid would land in a field."""
        points = _scatter(BUDA, 20) + _scatter(DEBRECEN, 10)
        clusters = cluster_home_bases(points)
        assert len(clusters) == 2
        assert clusters[0].activity_count == 20  # busiest first
        centroids = [(c.lat, c.lng) for c in clusters]
        assert min(haversine_km(c, BUDA) for c in centroids) < 1.0
        assert min(haversine_km(c, DEBRECEN) for c in centroids) < 1.0
        assert sum(c.weight for c in clusters) == pytest.approx(1.0)

    def test_holiday_one_off_is_noise_not_a_home_base(self):
        points = _scatter(BUDA, 20) + [(36.7213, -4.4214)]  # one run in Malaga
        clusters = cluster_home_bases(points)
        assert len(clusters) == 1

    def test_keeps_only_the_busiest_max_clusters(self):
        points = _scatter(BUDA, 12) + _scatter(DEBRECEN, 9) + _scatter((46.2530, 20.1414), 6)
        assert len(cluster_home_bases(points, max_clusters=2)) == 2

    def test_haversine_matches_known_distance(self):
        # Budapest -> Debrecen is ~195 km
        assert haversine_km(BUDA, DEBRECEN) == pytest.approx(195, abs=10)


class TestScoring:
    def test_habit_score_rewards_the_regular_saturday_runner(self):
        saturdays = [datetime(2026, 9, d, 8) for d in (5, 12, 19, 26)]
        weekdays = [datetime(2026, 9, d, 18) for d in (7, 8, 9, 10, 14, 15, 16, 17)]
        assert habit_score(saturdays + weekdays, target_weekday=5, target_hour=8) > 0.9
        assert habit_score(weekdays, target_weekday=5, target_hour=8) == 0.0

    def test_habit_score_respects_the_hour_window(self):
        evenings = [datetime(2026, 9, d, 20) for d in (5, 12, 19, 26)]
        assert habit_score(evenings, target_weekday=5, target_hour=8) == 0.0
        assert habit_score(evenings, target_weekday=5, target_hour=19) > 0.0

    def test_habit_score_of_no_history_is_zero_not_a_crash(self):
        assert habit_score([], target_weekday=5, target_hour=8) == 0.0

    def test_pace_score_is_neutral_when_unknown(self):
        assert pace_score(None, 300.0) == 0.5
        assert pace_score(300.0, None) == 0.5

    def test_pace_score_falls_off_with_difference(self):
        assert pace_score(300.0, 300.0) == 1.0
        assert pace_score(300.0, 330.0) == pytest.approx(0.5)
        assert pace_score(300.0, 400.0) == 0.0  # 1:40/km apart is not one session

    def test_distance_score_is_ratio_based(self):
        assert distance_score(10_000, 10_000) == 1.0
        assert distance_score(10_000, 12_000) > 0.6
        assert distance_score(10_000, 30_000) == 0.0

    def test_proximity_score_decays_across_the_radius(self):
        assert proximity_score(0.0, 20.0) == 1.0
        assert proximity_score(10.0, 20.0) == pytest.approx(0.5)
        assert proximity_score(25.0, 20.0) == 0.0

    def test_pace_helper_converts_to_seconds_per_km(self):
        assert pace_s_per_km(10_000, 3000) == pytest.approx(300.0)
        assert pace_s_per_km(0, 3000) is None

    def test_perfect_candidate_outranks_a_poor_one(self):
        saturdays = [datetime(2026, 9, d, 8) for d in (5, 12, 19, 26)]
        good = score_candidate(
            start_times=saturdays, target_weekday=5, target_hour=8,
            my_pace=300.0, their_pace=305.0, my_distance=12_000, their_distance=11_000,
            distance_km=2.0, radius_km=20.0,
        )
        poor = score_candidate(
            start_times=[datetime(2026, 9, 9, 19)], target_weekday=5, target_hour=8,
            my_pace=300.0, their_pace=380.0, my_distance=12_000, their_distance=30_000,
            distance_km=19.0, radius_km=20.0,
        )
        assert good.total > 0.85
        assert poor.total < 0.15
        assert good.total > poor.total
