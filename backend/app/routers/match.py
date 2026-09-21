from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.matching import find_candidates
from app.schemas import MatchFilters, MatchResponse

router = APIRouter(prefix="/match", tags=["match"])


@router.post("", response_model=MatchResponse)
async def match(
    filters: MatchFilters, session: AsyncSession = Depends(get_session)
) -> MatchResponse:
    """Deterministic search: filters in, ranked training partners out.

    The agent endpoint (POST /match/agent) wraps this same service and can relax
    the filters when the result set is thin.
    """
    results = await find_candidates(session, filters)
    return MatchResponse(filters_applied=filters, results=results)
