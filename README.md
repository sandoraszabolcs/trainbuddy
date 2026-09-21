# TrainBuddy

Find someone to train with: connect Strava, set your filters (sport, radius, gender,
pace, distance, which day), press **Find my TrainBuddy**, and get ranked training
partners whose usual training areas overlap yours and who habitually train on that day —
each with an LLM-written reason and a draft opening message.

Built as a portfolio piece for an AI-engineer role: FastAPI + React, a LangGraph agent
with tool use, RAG over pgvector, PostGIS geo matching, Docker/Terraform/CI.

> **Read `docs/DECISIONS.md` before changing anything.** The design is shaped by hard
> Strava API constraints (verified 2026-09-18) — most obviously that **the other athletes
> in the app are seeded rows we create**, because Strava only ever exposes the token
> owner's own data and forbids showing it to anyone else.

## Documentation

| File | What it holds |
|---|---|
| `docs/DECISIONS.md` | Every design decision (D1–D12) with the reasoning, plus the verified Strava constraints and the alternatives that were rejected |
| `docs/STATUS.md` | What is built and verified, what is not started, known issues and next actions |
| `docs/PLAN.md` | The approved 3-day implementation plan |
| `spike/` | The original November throwaway spike. **Not reused** — its `segments/explore` call stopped being available to non-Extended-Tier apps on 2026-09-01 |

## Architecture

```
React (Vite, TS)                     FastAPI                      Postgres 16
  filter panel  ──POST /match/agent──►  LangGraph agent  ──SQL──►  PostGIS (ST_DWithin)
  map + cards   ◄──── SSE steps ──────    4 tools                  pgvector (embeddings)
                                          │
                                          ├─ Strava OAuth + activity sync (own data only)
                                          └─ Claude (agent + card text) via langchain-anthropic
```

Matching, in order:
1. **Eligibility** — any of the candidate's home bases within the radius (default 20 km)
   of the search centre, in SQL via `ST_DWithin` on a GiST-indexed geography column.
2. **Home bases** — top 1–3 DBSCAN clusters of a person's activity start points, so
   someone who trains in two places matches in both.
3. **Ranking** — weighted: weekday/time habit 0.35, pace similarity 0.30, typical
   distance 0.20, proximity 0.15.
4. **Explanation** — Claude writes "why you match" and a draft opener.

## Quick start

```bash
# 1. database (PostGIS + pgvector, port 5433)
docker compose up -d db

# 2. backend
cd backend
uv venv --python 3.12 && uv pip install -e ".[dev]"
export DATABASE_URL="postgresql+psycopg://trainbuddy:trainbuddy@localhost:5433/trainbuddy"
.venv/bin/alembic upgrade head

# 3. seed the matching pool
#    real path (after connecting Strava):   python -m app.seed.route_pool
#    dev fallback (no Strava needed):
.venv/bin/python -m app.seed.route_pool --synthetic 47.4979,19.0402
.venv/bin/python -m app.seed.generate_athletes --count 100 --reset

# 4. run
.venv/bin/uvicorn app.main:app --reload --port 8000
```

```bash
# smoke test
curl -s localhost:8000/health
curl -s -X POST localhost:8000/match -H 'content-type: application/json' \
  -d '{"lat":47.4979,"lng":19.0402,"radius_km":20,"sport":"run",
       "target_date":"2026-09-19","target_hour":8,"limit":5}'
```

Tests: `cd backend && .venv/bin/pytest` (LLM eval cases are excluded by default; run them
with `-m eval`).

## Configuration

Copy `.env.example` to `.env`. Strava credentials come from
<https://www.strava.com/settings/api>; new apps start in Single Player Mode (1 athlete)
and can be self-upgraded to 10 in that dashboard.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | localhost:5433 | compose maps 5433 → 5432 to dodge a local Postgres |
| `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` | — | required for real sync |
| `ANTHROPIC_API_KEY` | — | without it, seeding falls back to templated persona text |
| `AGENT_MODEL` | `claude-opus-5` | set `claude-sonnet-5` to cut cost |
| `TEXT_MODEL` | `claude-haiku-4-5` | match reasons and openers |
| `ENABLE_DEV_LOGIN` | `false` | dev-only "log in as a seeded athlete"; keep off in cloud |

## Privacy and compliance

- A match card shows **derived, coarse data only**: an approximate area circle (never a
  point), pace band, typical distance, habitual days, persona text. No routes, no exact
  coordinates, no activity lists.
- Real Strava data is only ever shown back to the athlete it belongs to; everyone else in
  the pool is seeded. See `docs/DECISIONS.md` for the clause this respects and the
  unresolved question about the AI/ML clause.
