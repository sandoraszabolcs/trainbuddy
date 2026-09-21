# Decision record

Every decision below came out of a design interrogation before any code was written.
Each one records *what* was decided and *why*, so the reasoning does not have to be
re-derived. Dates are 2026 unless stated.

## The constraint that shapes everything

**Strava only ever exposes the token owner's own data.** Verified against the API
reference, the changelog and the API Agreement on 2026-09-18:

| Thing that looks like it would help | What it actually does |
|---|---|
| `GET /segments/explore` | Segment geometry only — no athlete data. **Restricted to approved Extended Access Tier developers (10k+ athletes) since 2026-09-01.** Not available to us. |
| `GET /segments/{id}` | Segment detail + `athlete_segment_stats` = *your own* PR only |
| `GET /segments/{id}/leaderboard` | **Removed from the API** in 2020/21 when leaderboards became subscriber-only |
| `GET /segment_efforts?segment_id=` | "the authenticated athlete's" efforts, and requires a Strava subscription |
| `GET /clubs/{id}/activities` | **Removed 2026-09-01.** Was anonymised anyway: first name + last initial, no id, no geo |
| athlete search | Does not exist. No endpoint enumerates athletes by area, segment or anything else |

Other facts that bind the build:

- **Base URL migration:** `https://www.strava.com/api/v3` → `https://api-v3.strava.com`,
  deadline January 2027. We use the new host from day one.
- **Athlete capacity:** new apps start in Single Player Mode (1 athlete). Self-service
  upgrade to **10 athletes** in the API Settings Dashboard; beyond that needs review.
- **Display restriction (API Agreement):** *"Strava Data provided by a specific user can
  only be displayed or disclosed in your Developer Application to that user. Strava Data
  related to other users, even if such data is publicly viewable on the Strava Platform,
  may not be displayed or disclosed."* A second clause adds *"not sharing a Strava user's
  data with other users ... without explicit consent"*. Reading the pair: the specific
  prohibition governs, and **user consent does not cure it** — it is Strava's licence,
  not the user's, doing the restricting. GDPR consent and this contract are different
  layers; passing one does not pass the other. The practical risk is **key revocation**,
  not litigation.
- **AI clause:** a Nov-2024 write-up claims the terms forbid using API data for AI/ML.
  The current agreement text contains no such clause. **Unresolved — re-read
  `strava.com/legal/api` before making anything public.**

**Consequence:** the other athletes in this app are rows we create ourselves (D1). No
real third-party data is ever displayed, so the display clause is never engaged.

### Alternatives that were considered and rejected

- **Garmin instead of Strava.** The Garmin Connect Developer Program "is available for
  enterprise use", explicitly not individuals/hobbyists; access is an application with
  ~2 business days to confirm and 1–4 weeks to integrate. Richer data (per-sample GPS,
  push webhooks), but unobtainable for a 3-day build and no clearer legal position.
- **GPX/FIT file import** (user exports their own activities and uploads them). Clean:
  no API agreement applies at all, works with Garmin *and* Strava data. **Considered and
  declined** in favour of keeping the live OAuth integration story.
- **Real multi-user** (friends connect via OAuth, capacity 10). Technically available,
  but showing athlete A's data to athlete B is what the display clause prohibits.
- **OpenStreetMap/Overpass for seed geometry.** Would remove the Strava dependency
  entirely. Declined — we keep Strava as the source (D1).

## Decisions

- **D1 Data** — Strava OAuth + activity sync only; **no GPX/FIT importer**. ~100 seeded
  athletes around the user's real home base. Seeded route geometry is derived from *the
  user's own synced polylines* (translated to each seeded athlete's home base, jittered,
  re-paced). Keeps Strava as the source without the now-restricted `segments/explore`,
  and the routes are genuinely local. Cached to a JSON fixture so re-seeding is offline.
- **D2 AI** — LangGraph agent behind the Find button with four tools: `find_candidates`
  (geo/SQL), `semantic_search` (pgvector over persona cards), `get_athlete_detail`,
  `search_training_kb`. It loops: thin results → it relaxes radius/day/pace itself,
  retries, and reports what it relaxed. Steps stream to the UI. An optional
  natural-language box pre-fills the filter form.
  *Why an agent at all:* a one-shot "sentence → filters" parser is function calling, not
  an agent. The self-relaxing retry loop is the part worth demoing.
- **D3 Matching** — a candidate is eligible when any of their home bases is within the
  radius (default 20 km, user-adjustable) of the search centre. Home bases = top 1–3
  DBSCAN clusters (~2 km eps) of activity start points, *not* a single centroid: most
  people train in more than one place and one centroid lands between them in a field.
  Ranking = weighted sum of weekday/time habit (0.35), pace similarity (0.30), typical
  distance similarity (0.20), proximity (0.15).
- **D4 Location** — search centre comes from **browser geolocation**, with a manual
  fallback (type a city / drag a pin) because ~1 in 3 users deny the prompt and it needs
  HTTPS (localhost exempt, Cloud Run fine). The user's own Strava history supplies their
  pace band and weekday habits, not the centre.
- **D5 Filters** — sport, radius, gender (Strava `sex`), pace band, typical-distance band.
  **No age filter: Strava exposes no age or birthday.** Age survives only as an optional
  self-declared card field. Pace and distance predict "can we actually train together"
  far better than age anyway.
- **D5b Display policy** — a match card shows **only derived, coarse** fields about
  another athlete: an approximate area *circle* (never a point), pace band, typical
  distance, habitual days, persona text. Never raw activity data, exact coordinates or
  route geometry. This is what a compliant production version could do.
- **D6 Contact** — in-app messaging only: an LLM-drafted, editable opener in a thread.
  **No WhatsApp handoff** (dropped on request; Strava exposes no phone numbers, so it
  could not be demoed honestly) and no accept/consent step. No `phone` column.
- **D7 Storage** — one Postgres with **PostGIS + pgvector**. Geography columns for
  points/routes, `ST_DWithin` for the radius gate, `vector` columns for embeddings.
- **D8 Models** — Claude via `langchain-anthropic`, behind config: `AGENT_MODEL`
  (default `claude-opus-5`) for the agent, `TEXT_MODEL` (default `claude-haiku-4-5`) for
  the cheap card text. *The plan originally said Sonnet 5 for the agent; switch
  `AGENT_MODEL=claude-sonnet-5` to halve cost.* Embeddings run locally via **fastembed**
  (bge-small, ONNX, ~50 MB) rather than sentence-transformers (~2 GB of torch), because
  the image has to deploy to Cloud Run.
- **D9 RAG** — two collections: (1) athlete persona cards for semantic matching;
  (2) a small **real training knowledge base** the agent cites when proposing what the
  joint session should be. Collection (2) is what makes this RAG rather than re-reading
  our own database — embedding machine-generated cards derived from the same DB the SQL
  tool queries adds no information, and an interviewer will say so.
- **D10 Auth** — real Strava OAuth (tokens + refresh stored server-side, session cookie)
  plus a feature-flagged **dev-only** "log in as <seeded athlete>" endpoint so both sides
  of a message thread can be demoed. Flag off in the cloud deploy.
- **D11 Ops** — docker-compose locally, GitHub Actions CI (ruff, mypy, pytest, image
  build), Terraform to **GCP Cloud Run** + Cloud SQL + Secret Manager + Artifact Registry.
  Structured JSON logs, request IDs, `/health`.
- **D12 Tests** — pure-function unit tests for geo/clustering/scoring; API tests with
  httpx against a Postgres testcontainer; agent tests with a stubbed LLM asserting
  tool-call order and the relax-retry behaviour; ~15-case eval file (NL query → expected
  filters/tools) behind a `pytest -m eval` marker.

## Out of scope (README "future work")

LoRA/PEFT fine-tuning · real multi-user via Strava approval · route-polyline overlap
scoring · push notifications · external-channel handoff (WhatsApp/email) with consent
and self-declared contact details.

## Why this project exists

Portfolio/interview piece for an AI-engineer role whose ad asks for: end-to-end AI apps,
scalable FastAPI REST APIs wired to a React front end, LLM/agent frameworks
(LangChain/LlamaIndex/Haystack), RAG with vector DBs, prompt engineering and fine-tuning,
cloud deployment with containers and IaC, DevOps/AIOps observability, and maintainable
tested code. Budget: ~3 days full-time.
