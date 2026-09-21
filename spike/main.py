from fastapi import FastAPI, Query, HTTPException
import requests
import os
from typing import List, Dict, Set
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

app = FastAPI(title="Strava Local Segment Efforts API")

STRAVA_ACCESS_TOKEN = os.getenv("STRAVA_ACCESS_TOKEN")

def strava_get(url, params=None):
    headers = {"Authorization": f"Bearer {STRAVA_ACCESS_TOKEN}"}
    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.json())
    return resp.json()


def get_local_segments(sw_lat, sw_lng, ne_lat, ne_lng, activity_type="running"):
    url = "https://www.strava.com/api/v3/segments/explore"
    params = {
        "bounds": f"{sw_lat},{sw_lng},{ne_lat},{ne_lng}",
        "activity_type": activity_type,
    }
    return strava_get(url, params=params)["segments"]


def get_segment_efforts(segment_id: int, start_date: datetime, end_date: datetime, per_page: int = 30):
    """
    Fetch segment efforts for the *authenticated athlete* on a specific segment.
    Only returns the athlete’s own efforts (if authorized).
    """
    url = "https://www.strava.com/api/v3/segment_efforts"
    params = {
        "segment_id": segment_id,
        "start_date_local": start_date.isoformat(),
        "end_date_local": end_date.isoformat(),
        "per_page": per_page
    }
    return strava_get(url, params=params)


@app.get("/local_efforts")
def local_efforts(
    lat: float = Query(..., description="Center latitude"),
    lng: float = Query(..., description="Center longitude"),
    radius_km: float = Query(2.0, description="Search radius in kilometers"),
    activity_type: str = Query("running", description="running or riding"),
    recent_days: int = Query(90, description="How far back to look for segment efforts"),
    per_segment: int = Query(30, description="Max efforts to fetch per segment")
):
    """
    Get segment efforts by the authenticated athlete for segments near your location.
    This shows which segments the athlete has run / ridden in the area.
    """

    # 1. Calculate bounding box
    lat_delta = radius_km / 111
    lng_delta = radius_km / (111 * abs(lat ** 0.5)) if lat != 0 else radius_km / 111
    sw_lat, sw_lng = lat - lat_delta, lng - lng_delta
    ne_lat, ne_lng = lat + lat_delta, lng + lng_delta

    # 2. Get local segments
    segments = get_local_segments(sw_lat, sw_lng, ne_lat, ne_lng, activity_type)

    # 3. Compute date range for efforts
    now = datetime.utcnow()
    start_date = now - timedelta(days=recent_days)
    end_date = now

    results = []

    # 4. For each segment, fetch the athlete's efforts
    for seg in segments:
        seg_id = seg["id"]
        efforts = get_segment_efforts(seg_id, start_date, end_date, per_segment)

        for effort in efforts:
            # effort is a DetailedSegmentEffort
            results.append({
                "segment_id": seg_id,
                "segment_name": seg.get("name"),
                "effort_id": effort.get("id"),
                "start_date": effort.get("start_date_local"),
                "elapsed_time": effort.get("elapsed_time"),
                "distance": effort.get("distance"),
                "average_cadence": effort.get("average_cadence"),
                "average_watts": effort.get("average_watts"),
                "average_heartrate": effort.get("average_heartrate"),
                "activity_id": effort.get("activity_id")
            })

    return {
        "center": {"lat": lat, "lng": lng},
        "radius_km": radius_km,
        "activity_type": activity_type,
        "recent_days": recent_days,
        "efforts_count": len(results),
        "efforts": results
    }
