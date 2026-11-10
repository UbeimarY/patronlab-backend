# PatronLab API

[![CI](https://github.com/UbeimarY/patronlab-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/UbeimarY/patronlab-backend/actions/workflows/ci.yml)

GraphQL API behind **PatronLab**, a pattern editor for artisans (embroidery, felt, leather,
laser-cut wood, and **Barniz de Pasto**). It stores every version of each pattern and offers
AI-assisted tools: a palette from a photo, a sketch turned into resin layers, design variations
(interactive and multi-objective), a color check, and a cutting plan that saves material.

The editor lives in [`patronlab-frontend`](https://github.com/UbeimarY/patronlab-frontend).

## Real-life problem

An artisan in Pasto designs a cushion cover in felt. Today she draws it on paper, picks colors by
eye, and cuts pieces wherever they fit on the sheet. PatronLab lets her draw the pattern, try color
combinations taken from a photo of her real materials, compare variations, and get an order to place
and cut the pieces that wastes less felt.

A *barnizador* plans a plate the same way: which colors of resin, in which order, how many sheets
of each color, and where to cut every piece. **Barniz mode** models exactly that (see
[Barniz de Pasto](#barniz-de-pasto)).

## Architecture

```
 Angular editor ──GraphQL (HTTPS, JWT)──▶ FastAPI + Strawberry ──▶ PostgreSQL (Neon)
                                               │
                                               └─▶ AI (in a worker thread, one job at a time):
                                                   k-means · contour tracing · genetic algorithm
                                                   · NSGA-II · nesting · CIEDE2000
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

Each version also stores its `mode`, piece count and layer count in columns, so the pattern list
(`mode`, `pieceCount`, `layerCount`) never loads the JSON documents.

## Barniz de Pasto

The *traditional knowledge and techniques associated with Pasto Varnish mopa-mopa of Putumayo and
Nariño* were inscribed by UNESCO in **2020** on the List of Intangible Cultural Heritage in **Need
of Urgent Safeguarding**. According to UNESCO, about **10 gatherers, 9 master carpenters and 36
varnishers** remain.

The process, and how the editor models each step:

| # | Step | In PatronLab |
|---|---|---|
| 1 | The buds of the mopa-mopa are gathered in Putumayo. | — |
| 2 | They are cleaned in boiling water and kneaded with a *maceta* on a *yunque*. | — |
| 3 | The resin is dyed with *anilina* (its natural color is olive green). | Each **layer** has one color: all of its pieces share it. |
| 4 | The wood is glued, sanded and painted with *esmalte*. | `object` (`plate`, `bowl`, `box`, `tray`) with its `baseColor`. |
| 5 | The resin is stretched into very thin **sheets**. | `optimizeLayout(perLayer: true, sheetWidth, sheetHeight)` counts sheets per color. |
| 6 | It is applied with the heat of the hand; **layers of colors are superposed**. | `layers` are ordered: index 0 is applied first, at the bottom. |
| 7 | It is **cut with a bisturí**. | Free-form `path` pieces; nesting of real outlines (`RASTER`) and a cut order. |
| 8 | It is fixed with heat. | — |

Gold or silver leaf is applied **before** the resin: `object.leaf` (`none`, `gold`, `silver`).

The demo account includes an original design, *Plato colibrí*: a 300 mm plate with black enamel
and gold leaf, a hummingbird and two radial flowers on four layers.

Sources: [UNESCO, element 01599](https://ich.unesco.org/es/USL/01599) ·
[Dossier Barniz de Pasto, Embassy of Colombia in Argentina](https://argentina.embajada.gov.co/sites/default/files/DOSSIER%20BARNIZ%20DE%20PASTO.pdf).

## Document contract (schema v2)

The frontend and the API share this JSON document (stored as JSONB). Units are millimeters.

```jsonc
{
  "schemaVersion": 2,
  "mode": "pattern",            // "pattern" | "barniz"
  "width": 400, "height": 400,
  "background": "#f6efe3",
  "object": null,               // barniz only: { "kind": "plate"|"bowl"|"box"|"tray",
                                //   "width", "height", "baseColor", "leaf": "none"|"gold"|"silver" }
                                // plate and bowl are round: width = height = diameter
  "layers": [ { "id": "l-1", "name": "Rojo", "color": "#b3202a", "visible": true, "locked": false } ],
  "groups": [ { "id": "g-1", "kind": "radial", "count": 6, "mirror": false, "sourceId": "s-1" } ],
  "shapes": [
    { "id": "s-1", "kind": "leaf", "x": 150, "y": 80, "width": 30, "height": 60, "rotation": 0,
      "fill": "#b3202a", "stroke": "#2b2420", "layerId": "l-1", "groupId": "g-1" },
    { "id": "s-2", "kind": "path", "x": 150, "y": 150, "width": 0, "height": 0, "rotation": 0,
      "fill": "#1f5fa0", "stroke": "#2b2420", "layerId": "l-1", "groupId": null,
      "points": [[-20, -10], [25, -5], [5, 20]] }   // relative to (x, y), closed polygon
  ]
}
```

Rules enforced by the API (`INVALID_DOCUMENT` with a list of `problems` otherwise):

* Kinds: `rect`, `ellipse`, `triangle`, `hexagon`, `star`, `leaf`, `path`. A `path` has 3 to 2000
  points (more is `TOO_MANY_POINTS`); its `width` and `height` are **recomputed** from its points.
* Every non-null `layerId` and `groupId` must exist; every group's `sourceId` must be a piece.
  Radial copies are stored as real pieces.
* Barniz: at most 12 layers and 1500 pieces. Pattern mode keeps the v1 limit of 400 pieces and has
  no `object`.
* **Version 1** documents (no `schemaVersion`) are upgraded by a pure function, `upgrade()`, every
  time they are read or validated: `mode: "pattern"`, `object: null`, empty `layers` and `groups`,
  and `layerId`/`groupId` `null` on every piece. `pattern.document` always returns v2.

## GraphQL API

Queries: `me`, `patterns`, `pattern(id) { document(version) versions }`, `materials`.
Mutations: `register`, `login`, `createPattern`, `savePattern` (needs `baseVersion`),
`restoreVersion`, `renamePattern`, `deletePattern`, **`duplicatePattern`**, and the AI tools below.
`PatternType` has `mode`, `pieceCount` and `layerCount`.

```graphql
input WeightsInput { balance: Float = 0.3, overlap: Float = 0.25, contrast: Float = 0.3, coverage: Float = 0.15 }
enum LayoutMethod { SKYLINE RASTER }

vectorizeImage(image: String!, width: Float!, height: Float!,
               colors: Int = 4, detail: Float = 0.5, minArea: Float = 20): VectorizeResult!
evolveVariations(document: JSON!, palette: [String!]!, favorites: [JSON!] = [],
                 weights: WeightsInput, seed: Int = 0): EvolveResult!
paretoVariations(document: JSON!, palette: [String!]!, seed: Int = 0): ParetoResult!
optimizeLayout(document: JSON!, rollWidth: Float!, spacing: Float = 3, perLayer: Boolean = false,
               sheetWidth: Float, sheetHeight: Float, method: LayoutMethod = SKYLINE): LayoutType!
analyzeColors(document: JSON!): ColorAnalysis!
duplicatePattern(id: ID!): PatternType!
# kept from v1: extractPalette(image, colors), generateVariations(document, palette, count, seed)
```

**Additions to the shared contract** (all additive; existing fields keep their meaning):

| Where | Field | Why |
|---|---|---|
| `PlacementType` | `angle: Float!` | RASTER rotates by steps of 15°, which `rotated` cannot express. The piece's outline, rotated by its own `rotation` plus `angle`, fits the box whose top-left corner is `(x, y)`. |
| `LayoutType` | `skylineLength`, `skylineWastePercent` | RASTER is compared with SKYLINE as well as with the baseline. |
| `LayoutType`, `EvolveResult`, `ColorAnalysis` | `elapsedMs` | Every AI result reports its time. |
| `LayoutType` | `notes: [String!]!` | Says when RASTER ran out of time and fell back to quarter turns. |
| `LayerPlan` | `layerId: ""` | Pieces without a layer are planned together. With sheets, sheet *n* starts at `y = n × sheetHeight`. `sheets` is 1 on a roll. |

**Errors** carry a stable `extensions.code` and a message in Colombian Spanish:
`UNAUTHENTICATED`, `NOT_FOUND`, `VERSION_CONFLICT`, `INVALID_DOCUMENT` (with `problems`),
`TOO_MANY_POINTS`, `TOO_MANY_SHAPES`, `IMAGE_TOO_LARGE`, `IMAGE_TOO_COMPLEX`, `RATE_LIMITED`
(with `retryAfter`, seconds), `TIMEOUT`, `PIECE_WIDER_THAN_MATERIAL`, `PIECE_LARGER_THAN_SHEET`,
`INVALID_ARGUMENT`, `INVALID_PALETTE`, … Unexpected errors are masked, so no internal detail
reaches the client. Queries are limited in depth and size.

Ready-to-run examples of every operation for GraphiQL: [docs/graphql-examples.md](docs/graphql-examples.md).

## AI module

Each technique is named for what it really is, returns a **baseline** to compare with, and has
its limits written down. None of them is a generative model: same input and seed, same output.

| Tool | Technique |
|---|---|
| `extractPalette` | **K-means** in RGB (scikit-learn): cluster centers are the palette, cluster sizes the share. |
| `vectorizeImage` | **K-means in CIELAB** + morphological opening + **marching squares** (`find_contours`) + **Douglas-Peucker** (`approximate_polygon`). |
| `generateVariations`, `evolveVariations` | **Genetic algorithm**: elitism, tournament selection, uniform crossover, mutation that shrinks over 18 generations. Interactive: favorites seed the population and are copied into 15 % of the genes; weights change the fitness. |
| `paretoVariations` | **NSGA-II**: non-dominated sorting + crowding distance, population 40, 25 generations, at most 12 designs on the front. |
| `optimizeLayout` | **Nesting** (bottom-left; SKYLINE on boxes at 0°/90°, RASTER on real outlines every 15°) and **cut order** as a traveling-salesman path (nearest neighbor + 2-opt). |
| `analyzeColors` | **CIEDE2000** between touching colors, nearest-name lookup in our own table, harmonies in **LCh**. |

### How each tool works, and its limits

**`vectorizeImage`**: from a sketch to resin sheets. The image (at most 4 MB and 8 MP) is reduced
to 1200 px on its longest side. K-means groups its pixels in CIELAB, where distances match how
different colors look. A cluster covering over 45 % of the image and touching its border is taken
as the background and dropped. Each other color is cleaned with an opening (no specks, no
one-pixel bridges), split into regions, traced and simplified. `detail` sets the Douglas-Peucker
tolerance (0.5 px at 1, 4 px at 0). Regions under `minArea` mm² are dropped (a bisturí cannot cut
them). The result has one layer per color, the largest at the bottom, named in Spanish, and `notes`
that explain every step. More than 1500 pieces, more than 2000 points in one piece, or more than
8 s is `IMAGE_TOO_COMPLEX`. *Limits:* holes are filled, so a ring becomes a disc (an upper layer
can cover it, but a hole that shows the background is lost). Gradients and shadows become bands
of flat color. The background rule fails on photos without a dominant border color.

**`evolveVariations`**: the genome has *color genes* and *motion genes*. In barniz mode a whole
layer is one color gene, so every sheet of a layer is the same resin, and a radial group is one
motion gene, so its copies keep their symmetry. Loose pieces may also scale (0.6×–1.6×) and rotate.
Pieces bigger than a quarter of the design never move. The fitness is computed on a 96-cell raster:
balance of the visual center of mass, little overlap, WCAG contrast (between touching pieces of
different layers, and against the object's enamel or the background) and coverage close to the
original's. `history` gives the best and average fitness of every generation; with elitism the
best never gets worse. *Limits:* the fitness encodes general design heuristics, not taste: the
artisan chooses. Favorites must come from the same design (same piece ids) or they are ignored.

**`paretoVariations`**: the same genome, with three separate objectives: balance, contrast and
material saving (`1 − length / original length` with SKYLINE on a roll as wide as the design). It
returns the non-dominated designs, at most 12, chosen to spread along the front. *Limits:* saving
is an estimate on boxes. It mostly comes from shrinking or turning pieces, which also changes the
design. The search stops at 15 s and returns what it found.

**`optimizeLayout`**: pieces go from largest to smallest; each goes where it ends nearest the start
of the material, then furthest left. SKYLINE packs bounding boxes. RASTER rasterizes outlines at
1 mm, grown by one cell, so pieces never really overlap (a test redraws them at 0.25 mm and counts
overlapping cells: zero). It tries 24 rotations, or 12 for shapes with half-turn symmetry. It finds
free spots with an FFT correlation on a conservative 4 mm grid and slides each piece at 1 mm.
`perLayer` packs every color on its own material; `sheetWidth`/`sheetHeight` count sheets.
The **baseline** is drawing order, shelf after shelf, no rotation, cut in drawing order. *Limits:*
heuristics, not optimal packings (the problem is NP-hard). RASTER has a 1–2 mm granularity; after
12 s the remaining pieces try only quarter turns (reported in `notes`). RASTER accepts up to 400
pieces.

**`analyzeColors`**: pairs of colors that touch (on a 192-cell raster), most similar first, with
ΔE2000. Below 10 they are flagged `tooSimilar`: two sheets that are hard to tell apart side by side.
Names come from our own table of about 40 Colombian Spanish color names. Their hex values were
chosen by the team, including barniz colors such as *rojo carmín* and *verde oliva*; it is not a
standard, so a name is the nearest entry. Harmonies (complementary, analogous ±30°, triadic ±120°)
turn the hue of the dominant color in LCh, keeping L and C, and lower C until the color exists in
sRGB.

### Measured, not claimed

Measured on the demo patterns with `seed: 0` (laptop, Python 3.11; the Fly machine is slower,
which is why every tool has a time limit).

**Nesting**, waste = 1 − pieces' real area / material used:

| Pattern | SKYLINE | RASTER | Baseline |
|---|---|---|---|
| *Cojín de hojas*, felt roll 500 mm | 300 mm · 26.2 % | 300 mm · 26.2 % | 383 mm · 42.2 % |
| *Plato colibrí*, roll 300 mm | 92.4 mm · 69.2 % | **72.0 mm · 60.4 %** | 142.6 mm · 80.0 % |
| 30 leaves, stars and triangles, roll 300 mm | 353 mm · 59.6 % | **288 mm · 50.5 %** | — · 68.1 % |

On the cushion the 300 × 300 mm front sets the length, so both methods tie. On the plate,
2-opt cuts the cutter's travel from 3920 mm to 898 mm. RASTER takes 0.3–1 s on these patterns;
SKYLINE under 10 ms.

**Evolution** (best fitness per generation, `evolveVariations` with default weights):

| Pattern | Original | Generation 0 | Generation 6 | Generation 12 | Generation 18 | Time |
|---|---|---|---|---|---|---|
| *Plato colibrí* (40 pieces) | 0.894 | 0.921 | 0.956 | 0.968 | **0.980** | 2.8 s |
| *Cojín de hojas* (10 pieces) | 0.850 | 0.885 | 0.893 | 0.908 | **0.921** | 0.9 s |

The average of the population rises too (plate: 0.858 → 0.926).

**Pareto front**: *Plato colibrí*: 12 designs in about 12 s; the most frugal saves 34.5 % of the
material length, the most contrasted reaches 0.993.

**Vectorization**: a 1200 × 1200 px sketch with 40 shapes in 5 colors (PNG or JPEG): about 1.5 s,
31 pieces, ~590 points. An 8 MP photo inside the Docker image with 1 CPU: 1.7 s.

### Limits on use

* 30 AI requests per minute per artisan (`RATE_LIMITED`, with `retryAfter`).
* One AI job at a time (`AI_CONCURRENCY`). The rest wait in line up to 20 s, then get
  `RATE_LIMITED`. The server uses about 190 MB, one heavy job peaks at about 350 MB in total, and
  three at once reached 547 MB, over the 512 MB machine. With one shared CPU, running them together
  would not finish them sooner anyway.
* Both limits live in the process: exact with the single Fly machine; several machines would need
  a shared store.

## Run locally

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/) and PostgreSQL.

```bash
uv sync
cp .env.example .env              # then fill in your local values
uv run alembic upgrade head
uv run python -m patronlab.cli seed-demo   # optional: demo artisan + starter patterns
uv run uvicorn patronlab.app:create_app --factory --reload
```

GraphiQL: <http://localhost:8000/graphql>.

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest -q                  # AI unit tests + GraphQL integration tests on PostgreSQL
```

A throwaway PostgreSQL for the tests:

```bash
docker run -d --name patronlab_test_db -e POSTGRES_USER=patronlab -e POSTGRES_DB=patronlab_test \
  -e POSTGRES_HOST_AUTH_METHOD=trust -p 5440:5432 postgres:17
# TEST_DATABASE_URL=postgresql+asyncpg://patronlab@localhost:5440/patronlab_test
```

Optional settings: `AI_REQUESTS_PER_MINUTE` (30), `AI_CONCURRENCY` (1), `GRAPHIQL` (true).

## Deploy (Fly.io + Neon)

First time:

```bash
fly launch --no-deploy --copy-config
fly secrets set DATABASE_URL="<Neon connection string>" JWT_SECRET="$(openssl rand -hex 32)"
```

Every release:

```bash
fly deploy --ha=false --app patronlab-api-ubeimar
# Adds the starter patterns the demo account is missing; an existing account is left untouched.
fly ssh console -a patronlab-api-ubeimar -C "env PATRONLAB_DEMO_PASSWORD=… python -m patronlab.cli seed-demo"
```

Migrations run when the machine starts; this release adds two summary columns to
`pattern_versions` and fills them from the documents already saved. To add the frontend's address,
edit `CORS_ORIGINS` in `fly.toml` and deploy again.

The image is about 520 MB on disk and about 160 MB compressed, which is what Fly pulls. SciPy,
scikit-learn, scikit-image and NumPy are most of it; their bundled test suites are removed at
build time.

## Project status

Course project for *Programación Orientada a la Web*, Universidad Cooperativa de Colombia, Pasto.
