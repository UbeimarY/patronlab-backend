# PatronLab API

[![CI](https://github.com/UbeimarY/patronlab-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/UbeimarY/patronlab-backend/actions/workflows/ci.yml)

GraphQL API behind **PatronLab**, a pattern editor for artisans (embroidery, felt, leather,
laser-cut wood). It stores every version of each pattern and offers three AI-assisted tools:
a palette from a photo, design variations, and a cutting plan that saves material.

The editor lives in [`patronlab-frontend`](https://github.com/UbeimarY/patronlab-frontend).

## Real-life problem

An artisan in Pasto designs a cushion cover in felt. Today she draws it on paper, picks colors by
eye, and cuts pieces wherever they fit on the sheet. PatronLab lets her draw the pattern, try color
combinations taken from a photo of her real materials, compare variations, and get an order to place
and cut the pieces that wastes less felt.

## Architecture

```
 Angular editor ──GraphQL (HTTPS, JWT)──▶ FastAPI + Strawberry ──▶ PostgreSQL (Neon)
                                               │
                                               └─▶ AI: k-means · evolutionary search · nesting
```

| Piece | Choice | Why |
|---|---|---|
| API | **GraphQL** (Strawberry on FastAPI) | Each screen asks for exactly what it shows in one request; typed and self-documenting (GraphiQL at `/graphql`). |
| Database | PostgreSQL, documents in **JSONB** | A pattern is a document; versions are immutable snapshots. |
| Auth | Argon2id + JWT (7 days) | Public sign-up; every pattern is private to its owner. |
| Deploy | Docker on **Fly.io**, database on **Neon** | Always-on machine, migrations run on start. |

### Versioning and concurrency

Every save creates a new, immutable version. A save must say which version it started from
(`baseVersion`): if someone saved in the meantime (another tab or device), the API answers
`VERSION_CONFLICT` with the current number instead of silently overwriting work. A row lock
serializes concurrent saves, and a unique `(pattern, number)` constraint is the last line of
defense; a test fires three saves at once and checks exactly one wins. Restoring an old version
saves it as the newest one, so history is never lost.

## AI module

Three techniques, each named for what it really is:

| Tool | Technique | What it does |
|---|---|---|
| `extractPalette` | **K-means clustering** (unsupervised learning, scikit-learn) | Every pixel of a photo is a point in RGB space; the cluster centers are the palette, the cluster sizes say how dominant each color is. |
| `generateVariations` | **Evolutionary search** (genetic algorithm) | A population of candidates recolors (only with the palette) and slightly moves, resizes and rotates the shapes. Tournament selection, uniform crossover and mutation for 18 generations; an explicit fitness function decides. |
| `optimizeLayout` | **Combinatorial optimization** | Nesting on a roll with the skyline bottom-left heuristic (0°/90°), and cutting order as a traveling-salesman path: nearest neighbor improved with 2-opt. |

**Fitness of a design** (computed on a 96-cell raster): balance of the visual center of mass
(30 %), little overlap between shapes (25 %), WCAG contrast between touching shapes and against
the background (30 %), and covered area close to the original's (15 %).

**Measured, not claimed:** every result is returned next to a baseline, so the gain is visible.
On a 14-piece test pattern, variations raised the fitness from 0.73 to 0.89, nesting cut the waste
from 65 % to 56 % against a naive shelf layout (drawing order, no rotation), and the 2-opt route
reduced the cutter's travel from 1 688 mm to 774 mm compared with drawing order.

**Limitations, stated plainly:** the fitness function encodes general design heuristics, not
taste; the artisan always chooses. Nesting packs bounding boxes (with a cutting margin), so curved
pieces leave some unavoidable gaps. Results are deterministic for a given seed.

## API at a glance

```graphql
mutation { login(email: "artesana@demo.co", password: "…") { token } }

query { patterns { id name currentVersion updatedAt } }

mutation Save($input: SavePatternInput!) {
  savePattern(input: $input) { currentVersion }   # baseVersion required
}

mutation Layout($doc: JSON!) {
  optimizeLayout(document: $doc, rollWidth: 900) { wastePercent baselineWastePercent cutOrder }
}
```

Errors carry a stable `extensions.code` (`UNAUTHENTICATED`, `NOT_FOUND`, `VERSION_CONFLICT`,
`INVALID_DOCUMENT`, …). Unexpected errors are masked, so no internal detail reaches the client.
Queries are limited in depth and size.

## Run locally

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/) and PostgreSQL.

```bash
uv sync
cp .env.example .env              # then fill in your local values
uv run alembic upgrade head
uv run python -m patronlab.cli seed-demo   # optional: demo artisan + starter pattern
uv run uvicorn patronlab.app:create_app --factory --reload
```

GraphiQL: <http://localhost:8000/graphql>.

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest -q                  # AI unit tests + GraphQL integration tests on PostgreSQL
```

## Deploy (Fly.io + Neon)

```bash
fly launch --no-deploy --copy-config
fly secrets set DATABASE_URL="<Neon connection string>" JWT_SECRET="$(openssl rand -hex 32)"
fly deploy --ha=false
```

Migrations run when the machine starts. To add the frontend's address, edit `CORS_ORIGINS` in
`fly.toml` and deploy again.

## Project status

Course project for *Programación Orientada a la Web*, Universidad Cooperativa de Colombia, Pasto.
