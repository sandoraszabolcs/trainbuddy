"""Strava HTTP client: OAuth exchange, refresh-on-expiry, rate-limit aware.

Only ever reads the token owner's own data - that is all the API exposes, and
all the API Agreement permits us to show back to them.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class StravaError(RuntimeError):
    pass


class StravaRateLimited(StravaError):
    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"Strava rate limit hit; retry in {retry_after_s}s")
        self.retry_after_s = retry_after_s


def authorize_url(state: str) -> str:
    params = httpx.QueryParams(
        client_id=settings.strava_client_id,
        redirect_uri=settings.strava_redirect_uri,
        response_type="code",
        approval_prompt="auto",
        scope=settings.strava_scope,
        state=state,
    )
    return f"{settings.strava_oauth_base}/authorize?{params}"


async def exchange_code(code: str) -> dict[str, Any]:
    """Trade an OAuth code for tokens + the athlete profile."""
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{settings.strava_oauth_base}/token",
            data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
    if response.status_code != 200:
        raise StravaError(f"token exchange failed ({response.status_code}): {response.text[:200]}")
    return response.json()


async def refresh_token(refresh: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{settings.strava_oauth_base}/token",
            data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code != 200:
        raise StravaError(f"token refresh failed ({response.status_code}): {response.text[:200]}")
    return response.json()


def token_is_expired(expires_at: datetime, skew: timedelta = timedelta(minutes=5)) -> bool:
    """True if the token is gone or about to be, so callers refresh before using it."""
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return datetime.now(UTC) + skew >= expires_at


class StravaClient:
    """Authenticated read client. One instance per athlete per sync."""

    def __init__(self, access_token: str, *, max_retries: int = 2) -> None:
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._max_retries = max_retries

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{settings.strava_api_base}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            for attempt in range(self._max_retries + 1):
                response = await client.get(url, headers=self._headers, params=params)
                if response.status_code == 429:
                    # ~100 reads / 15 min, 1000 / day. Back off rather than hammer.
                    retry_after = int(response.headers.get("retry-after", "900"))
                    if attempt == self._max_retries:
                        raise StravaRateLimited(retry_after)
                    logger.warning("strava rate limited, sleeping %ss", min(retry_after, 60))
                    await asyncio.sleep(min(retry_after, 60))
                    continue
                if response.status_code >= 500 and attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                if response.status_code != 200:
                    raise StravaError(f"GET {path} -> {response.status_code}: {response.text[:200]}")
                return response.json()
        raise StravaError(f"GET {path} exhausted retries")

    async def athlete(self) -> dict[str, Any]:
        return await self.get("/athlete")

    async def activities(self, *, per_page: int = 100, max_pages: int = 5) -> list[dict[str, Any]]:
        """Recent activities, newest first. Capped so one sync can't burn the quota."""
        collected: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            batch = await self.get("/athlete/activities", {"per_page": per_page, "page": page})
            if not batch:
                break
            collected.extend(batch)
            if len(batch) < per_page:
                break
        return collected
