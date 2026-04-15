# TT Policy Tracker

TurboTenant Legislative Policy Tracker — an internal tool that monitors federal, state, and local legislative activity relevant to rental housing and delivers AI-summarized digests.

## Phase 0 Scope

- **Adapters:** Open States (OH + CO), Congress.gov, Federal Register
- **AI Pipeline:** Haiku relevance classifier → Sonnet summarizer → geotagger
- **Delivery:** Weekly email digest + internal web dashboard
- **Target:** Internal TT team (10 users on daily/weekly digests)

## Quick Start

### Docker Compose (recommended)

```bash
cp .env.example .env
# Fill in your API keys in .env

docker compose up -d
```

Services:
- **API:** http://localhost:8000 (FastAPI)
- **Dashboard:** http://localhost:3000 (Next.js — run separately, see below)
- **Mailpit:** http://localhost:8025 (local email testing UI)
- **Postgres:** localhost:5432

### Run Pipelines

```bash
# Ingest from all adapters (last 7 days)
docker compose exec worker python -m cli.ingest --days-back 7

# Ingest from a single adapter
docker compose exec worker python -m cli.ingest --adapter openstates --days-back 30

# Run enrichment on un-processed documents
docker compose exec worker python -m cli.enrich --batch-size 100

# Send weekly digest (creates default subscription if none exist)
docker compose exec worker python -m cli.digest --frequency weekly --force
```

### Web Dashboard

```bash
cd web
npm install
npm run dev
```

Open http://localhost:3000. The dashboard proxies API calls to the FastAPI backend.

### Local Development (without Docker)

```bash
# Requires Python 3.11+ and Postgres 16 with pgvector
pip install -e ".[dev]"

# Run migrations
alembic upgrade head

# Start API
uvicorn api.main:app --reload

# Run pipelines
python -m cli.ingest --days-back 7
python -m cli.enrich
python -m cli.digest --frequency weekly --force
```

## Architecture

```
Ingestion (adapters) → Raw Document Store → AI Enrichment Pipeline → Postgres + pgvector → Digest Builder / API / Dashboard
```

See the full build plan for detailed architecture docs.

## Eval Harness

```bash
# Run with live API (requires ANTHROPIC_API_KEY)
pytest tests/eval/ -v

# Run without API (format validation only)
SKIP_LIVE_EVAL=1 pytest tests/eval/ -v
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENSTATES_API_KEY` | Yes | Open States API v3 key |
| `CONGRESS_API_KEY` | Yes | Congress.gov / api.data.gov key |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Haiku + Sonnet |
| `POSTMARK_TOKEN` | No | Postmark server token (falls back to log-only mode) |
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `DIGEST_RECIPIENT` | No | Default digest recipient email |

## Topics Tracked

1. Landlord-tenant laws
2. Security deposit rules
3. Eviction procedures / moratoria
4. Source-of-income (SOI) discrimination
5. Rental registration / licensing / inspection
6. Background & credit screening restrictions
7. Application fee limits
8. Rent control / rent stabilization
9. Habitability / code enforcement
10. Fair housing updates
