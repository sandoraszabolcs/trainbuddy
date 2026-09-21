# TrainBuddy POC — implementation plan

## Context
Build a training-partner matcher (React + FastAPI) in ~3 days, as a portfolio/interview piece for an
AI-engineer role whose ad calls out: end-to-end AI apps, FastAPI REST APIs + React, LLM/agent frameworks
(LangChain/LangGraph), RAG with vector DBs, prompt engineering, cloud deploy with IaC, DevOps/observability,
and maintainable tested code.

Product: the user logs in with Strava; the app derives their training profile from real activity history.
They set filters (sport, radius, gender, pace/distance band), press **Find my TrainBuddy**, and get ranked
partners whose usual training areas sit within the radius of them, who habitually train on the chosen
day/time, with an LLM-written reason and a draft opener they can edit and send in-app.

### Hard external constraints (verified 2026-09)
Strava exposes **only the token owner's own data**: `/segments/{id}` gives only your own
`athlete_segment_stats`; `/segments/{id}/leaderboard` was removed from the API in 2020/21; `/segment_efforts`
returns "the authenticated athlete's" efforts and needs a Strava subscription; there is no athlete-search
endpoint.

Recent changes that bind this build:
- **2026-09-01: `segments/explore` restricted to approved Extended Access Tier developers** (10k+ athletes)
  and the Club Activities/Members/Admins endpoints were removed. The spike's explore call is therefore dead
  for us — seeding must not depend on it.
- Base URL migrates `https://www.strava.com/api/v3` → `https://api-v3.strava.com` (deadline Jan 2027).
  **Use the new base URL from day 1.**
- Athlete capacity: new apps start in Single Player Mode (1 athlete); **self-service upgrade to 10** is
  available in the API Settings Dashboard; beyond that needs review.
- API Agreement: *"Strava Data provided by a specific user can only be displayed or disclosed in your
  Developer Application to that user."* Consent does not appear to cure this — it is Strava's licence, not
  the user's, doing the restricting. A Nov-2024 write-up also claims the terms forbid using API data for
  AI/ML; the current agreement text does not contain such a clause. **Re-read `strava.com/legal/api`
  before making anything public.** Practical risk is key revocation, not litigation.

=> Other athletes are **seeded rows in our own Postgres**, flowing through the identical schema and code path
as the real synced user. Nothing real about a third party is ever displayed. The constraint and the design
around it is itself an interview talking point (decision record in the README).

## Decisions
- **D1 Data** — **Strava OAuth + activity sync only** (no GPX/FIT importer). ~100 seeded athletes around the
  user's real home base. Seeded route geometry comes from **the user's own synced activity polylines**
  (pooled, then jittered start points / trimmed / extended / re-paced per seeded athlete) — keeps Strava as
  the source without the now-restricted `segments/explore`, and the routes are genuinely local because they
  are places the user actually trains. Pool cached to a JSON fixture so re-seeding needs no network.
  Persona text per athlete written by an LLM at seed time.
- **D2 AI** — LangGraph agent behind the Find button: tools `find_candidates` (geo/SQL filters),
  `semantic_search` (pgvector over persona cards), `get_athlete_detail`, `search_training_kb`. It loops: when
  results are thin it relaxes radius/day/pace itself, retries, and reports what it relaxed
  ("no women cycling within 20 km on Sat; widened to 30 km → 4 matches"). Steps stream to the UI.
  Optional NL box above the form pre-fills the filters.
- **D3 Matching** — candidate eligible when any of their home bases is within the radius (default 20 km,
  slider) of the search centre. Home bases = top 1–3 DBSCAN clusters (~2 km eps) of activity start points.
  Rank = weighted sum of weekday/time-of-day habit frequency, pace similarity, typical-distance similarity,
  proximity, (+ semantic similarity when an NL query was given). Then Haiku writes "why you match" + opener.
- **D4 Location** — search centre from **browser geolocation**; fallback (denied/unavailable) = type a city or
  drag a pin. Needs HTTPS in production (Cloud Run is fine). The user's own Strava history supplies their
  pace band and weekday habits, not the centre.
- **D5 Filters** — sport, radius, gender (Strava `sex`), pace band, typical-distance band. **No age filter**:
  Strava exposes no age/birthday; age is kept only as an optional self-declared card field.
- **D5b Display policy** — a match card shows **only derived, coarse** fields about the other athlete:
  approximate area (a circle, never a point or a polyline), pace band, typical distance, habitual days,
  persona text. Never raw activity data, exact coordinates or route geometry. This is what a compliant
  production version could do, and it is recorded as a deliberate privacy decision in the README.
- **D6 Contact** — in-app only: messages table + LLM-drafted editable opener, sent and shown in a thread.
  No WhatsApp handoff and no accept/consent step (dropped: Strava exposes no phone numbers, so it could not be
  demoed honestly). No `phone` column on `athlete`.
- **D7 Storage** — one Postgres with **PostGIS + pgvector**: routes/start points as `geography`,
  `ST_DWithin` for the radius gate, embeddings in `vector` columns.
- **D8 Models** — Claude Sonnet 5 for the agent, Haiku 4.5 for explanation/opener text, via
  `langchain-anthropic`, behind a thin provider interface. Embeddings local via
  `sentence-transformers` (bge-small) — no embedding cost, no second vendor.
- **D9 RAG** — two collections: (1) athlete persona cards for semantic matching; (2) a small real training
  knowledge base (running/cycling training + group-etiquette articles) the agent cites when proposing what the
  joint session should be. Collection (2) is what makes this RAG rather than re-reading our own DB.
- **D10 Auth** — real Strava OAuth (tokens + refresh stored server-side, session cookie) plus a
  feature-flagged, **dev-only** "log in as <seeded athlete>" endpoint to demo both sides of a thread; flag off
  in the cloud deploy.
- **D11 Ops** — docker-compose local, GitHub Actions CI (ruff, mypy, pytest, image build), Terraform to
  **GCP Cloud Run** + Cloud SQL Postgres + Secret Manager + Artifact Registry. Structured JSON logs, request
  IDs, `/health`.
- **D12 Tests** — pure-function unit tests for geo/clustering/scoring; API tests with httpx against a Postgres
  testcontainer; agent tests with a stubbed LLM asserting tool-call order and relax-and-retry; ~15-case eval
  file (NL query → expected filters/tools) behind a pytest marker.
- **Out of scope** (README "future work"): LoRA/PEFT fine-tuning, real multi-user via Strava approval,
  route-polyline overlap scoring, push notifications, external-channel handoff (WhatsApp/email) with
  consent + self-declared contact details.

## Repo layout
```
trainBuddy/
  backend/app/
    main.py config.py db.py models.py schemas.py deps.py logging.py
    routers/   auth.py match.py athletes.py messages.py health.py
    strava/    client.py (httpx + token refresh)  sync.py  polyline.py
    geo/       clustering.py (DBSCAN)  scoring.py
    ai/        llm.py agent.py tools.py embeddings.py rag.py prompts.py
    seed/      route_pool.py generate_athletes.py fixtures/route_pool.json
  backend/alembic/  backend/tests/  backend/pyproject.toml (uv, ruff, mypy)
  frontend/src/  api/ components/{FilterPanel,MapView,MatchCard,AgentTrace,MessageThread} hooks/
  infra/         terraform (cloud run, cloud sql, secret manager, artifact registry)
  db/Dockerfile  docker-compose.yml  Dockerfile.api  Dockerfile.web
  .github/workflows/ci.yml  README.md
```
The existing `/home/szabolcs/code/trainBuddy/main.py` is a spike and is **not reused**: `segments/explore` is
no longer available to us (2026-09-01 restriction), the per-segment effort loop would blow the rate limit,
`lng_delta` at line 62 uses `lat ** 0.5` instead of `cos(radians(lat))`, and `utcnow()` is deprecated. Move it
to `spike/` for reference only. Keep `.env`; add `.env.example` and make sure `.env` is gitignored before the
first commit (it currently holds a live-ish Strava token).

## Day 1 — data + geo core
1. Scaffold backend (uv, FastAPI app factory, pydantic-settings, ruff/mypy), `docker-compose.yml`.
   **Gotcha:** no public image ships PostGIS *and* pgvector — `db/Dockerfile` = `FROM postgis/postgis:16-3.4`
   + `apt-get install postgresql-16-pgvector`; init SQL creates both extensions. Cloud SQL supports both natively.
2. SQLAlchemy models + Alembic: `athlete` (strava_id, sex, sport, pace_band, typical_distance_m, persona_text,
   is_seeded), `home_base` (athlete_id, point geography, weight), `activity` (athlete_id, sport,
   start_point geography, route geography, start_time_local, distance_m, moving_time_s),
   `athlete_embedding` (vector), `kb_chunk` (text, vector), `message`, `match_request` (audit of agent runs).
   GiST indexes on geography columns, IVFFlat on vectors.
3. `strava/client.py`: httpx client against **`https://api-v3.strava.com`**, OAuth code exchange,
   refresh-on-expiry, rate-limit-aware retry (~100 req/15 min). `strava/sync.py`: paginate
   `/athlete/activities`, decode `summary_polyline` (`polyline` lib) → PostGIS. Scope `activity:read_all`,
   and honour Strava privacy: skip private activities unless the user opts in.
4. `geo/clustering.py`: DBSCAN (haversine metric, eps ≈ 2 km) over start points → top 3 home bases.
   `geo/scoring.py`: weekday/time habit frequency, pace band, distance band, proximity score, weighted total.
   Pure functions, unit-tested.
5. `seed/route_pool.py`: build the route pool from the user's own synced polylines → `fixtures/route_pool.json`
   (one-off, offline afterwards). `seed/generate_athletes.py`: ~100 athletes, 1–3 home bases each, 20–80
   activities sampled from the pool with jittered starts and varied distance/pace, plausible weekday/hour
   patterns, LLM persona text.
   **Sanity check:** the seeded athletes must not all cluster on the same handful of routes — vary start
   offsets and direction, and assert in a test that home-base spread covers the search radius.
6. `POST /match` deterministic version: filters → `ST_DWithin` candidate query → scoring → ranked JSON.

## Day 2 — AI layer + frontend
7. `ai/embeddings.py` (sentence-transformers) + persona-card embedding at seed time; `ai/rag.py` ingests the
   training KB (markdown files in repo → chunk → embed → `kb_chunk`), with a `search_training_kb` retriever.
8. `ai/tools.py` + `ai/agent.py`: LangGraph ReAct-style graph over the four tools, max ~6 steps, a
   `relaxations[]` accumulator, structured output (matches + relaxations + citations). Prompts in
   `ai/prompts.py`; Sonnet 5 for the agent, Haiku 4.5 for card text.
9. `POST /match/agent` with SSE streaming of steps; `GET /athletes/{id}`.
10. Frontend (Vite + React + TS + TanStack Query): geolocation hook with manual fallback, FilterPanel
    (sport, radius slider, gender, pace, distance, date + time window), Find button, MapLibre/Leaflet map
    showing the search circle + candidate home-base pins, MatchCard (reason, habit chart, opener draft),
    AgentTrace panel consuming the SSE stream.

## Day 3 — messaging, quality, ship
11. Messaging: `POST /messages` + `GET /messages/{athlete_id}` thread view, opener prefilled from the match
    card and editable; dev-only impersonation endpoint behind `ENABLE_DEV_LOGIN` to show both sides.
12. Tests per D12 + `logging.py` (JSON logs, request-id middleware), `/health` with DB + model checks.
13. `Dockerfile.api` / `Dockerfile.web`, `.github/workflows/ci.yml` (ruff, mypy, pytest, build),
    `infra/` Terraform: Artifact Registry, Cloud SQL (PostGIS + pgvector flags), Secret Manager
    (Strava + Anthropic keys), Cloud Run services, least-privilege service account.
14. README: architecture diagram, the Strava-constraint decision record, scoring formula, agent tool list,
    local + cloud run instructions, 2-minute demo script, future work.

## Verification
- OAuth round-trip: connect a real Strava account, `/athlete/activities` syncs, polylines land in PostGIS,
  token refresh works after expiry (force it by clearing `expires_at`).
- `docker compose up` → `alembic upgrade head` → `python -m app.seed.route_pool` →
  `python -m app.seed.generate_athletes` → open the app, allow geolocation, press Find: ranked matches appear
  with reasons.
- A match card exposes no raw route, no exact coordinates and no activity list (assert it in an API test).
- `pytest` green: geo maths, API (testcontainer), agent tool-order and relax-retry with a stubbed LLM.
- `pytest -m eval` → ≥80% of the 15 NL cases map to the expected filters/tools.
- Deliberate empty-result search (e.g. gender + 5 km + weekday nobody trains) → agent visibly relaxes and
  explains; verified in both the UI trace and the `match_request` audit row.
- `curl /health` OK; logs are single-line JSON with request ids.
- `terraform apply` → the Cloud Run URL serves the app against Cloud SQL; dev-login flag off there.
- Real-data sanity check: your own synced activities produce sensible home bases and pace band
  (eyeball the map circles against where you actually train).
