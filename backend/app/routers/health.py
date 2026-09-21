from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter(tags=["ops"])


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    checks: dict[str, object] = {"api": "ok"}
    try:
        await session.execute(text("SELECT 1"))
        extensions = await session.execute(
            text("SELECT extname FROM pg_extension WHERE extname IN ('postgis', 'vector')")
        )
        found = sorted(row[0] for row in extensions)
        checks["db"] = "ok"
        checks["extensions"] = found
        if len(found) < 2:
            checks["db"] = "degraded: missing postgis/vector extension"
    except Exception as exc:  # noqa: BLE001 - health must report, not raise
        checks["db"] = f"error: {exc.__class__.__name__}"
    status = "ok" if all(v == "ok" for k, v in checks.items() if k in {"api", "db"}) else "degraded"
    return {"status": status, "checks": checks}
