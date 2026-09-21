"""Home-base detection.

An athlete rarely has one 'usual area' - home, office, weekend spot. We cluster
activity start points with DBSCAN (haversine metric) and keep the busiest few
clusters, so someone who trains in two places matches in both.
"""

from dataclasses import dataclass

import numpy as np
from sklearn.cluster import DBSCAN

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class HomeBaseCluster:
    lat: float
    lng: float
    activity_count: int
    weight: float  # share of the athlete's clustered activities


def cluster_home_bases(
    points: list[tuple[float, float]],
    eps_km: float = 2.0,
    min_activities: int = 3,
    max_clusters: int = 3,
) -> list[HomeBaseCluster]:
    """Cluster (lat, lng) start points into at most `max_clusters` home bases.

    Points DBSCAN labels as noise are ignored: a one-off holiday run should not
    create a home base. Returns clusters ordered by activity count, descending.
    """
    if not points:
        return []

    radians = np.radians(np.asarray(points, dtype=float))
    labels = DBSCAN(
        eps=eps_km / EARTH_RADIUS_KM,
        min_samples=min_activities,
        metric="haversine",
    ).fit_predict(radians)

    clustered = labels[labels >= 0]
    if clustered.size == 0:
        return []

    clusters: list[HomeBaseCluster] = []
    for label in set(clustered.tolist()):
        member_radians = radians[labels == label]
        lat, lng = np.degrees(_spherical_mean(member_radians))
        clusters.append(
            HomeBaseCluster(
                lat=float(lat),
                lng=float(lng),
                activity_count=int(member_radians.shape[0]),
                weight=float(member_radians.shape[0]) / float(clustered.size),
            )
        )

    clusters.sort(key=lambda c: c.activity_count, reverse=True)
    return clusters[:max_clusters]


def _spherical_mean(points_rad: np.ndarray) -> np.ndarray:
    """Mean of lat/lng in radians via 3D unit vectors, so it survives the date line."""
    lat, lng = points_rad[:, 0], points_rad[:, 1]
    x = np.cos(lat) * np.cos(lng)
    y = np.cos(lat) * np.sin(lng)
    z = np.sin(lat)
    mean_x, mean_y, mean_z = x.mean(), y.mean(), z.mean()
    hyp = np.hypot(mean_x, mean_y)
    return np.array([np.arctan2(mean_z, hyp), np.arctan2(mean_y, mean_x)])


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in km between two (lat, lng) pairs."""
    lat1, lng1, lat2, lng2 = np.radians([a[0], a[1], b[0], b[1]])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlng / 2) ** 2
    return float(2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(h)))
