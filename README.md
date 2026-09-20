# TEM Platform

A multi-tenant **Threat Exposure Management** platform, built as a modular monolith.

Four modules — **ASM**, **Threat Intelligence**, **Dark Web Monitoring**, **Brand Protection** —
plugged into one shared pipeline:

```
targets → jobs → findings → alerts → analytics
```

## Where the work is

Everything is tracked here, in this repository:

- **[Issues](https://github.com/emad-anwer/tem-platform/issues)** — one issue per task. Owner,
  reviewer, effort, dependencies and acceptance criteria are all on the issue, along with a
  **Search for** list of the concepts that task needs.
- **[Milestones](https://github.com/emad-anwer/tem-platform/milestones)** — one per week. Your
  week's scope is its milestone.
- **Pinned keyword issue** — each week has one, listing the concepts you're expected to be able
  to defend at Thursday's demo.

Picking up a task: assign yourself, move it in progress, branch as
`w<week>/<short-name>`, open a PR that closes the issue. [CONTRIBUTING.md](CONTRIBUTING.md) has
the details.

If a task's description is ambiguous, say so **on the issue** rather than guessing in silence —
that's a real engineering skill, not an admission of confusion.

## Stack

Python 3.11 · FastAPI · PostgreSQL 16 · Clickhouse . Redis 7 · SQLAlchemy 2.0 (async) · Alembic · Docker Compose · `just` · `uv` · Ruff 

---

## Prerequisites

You need these installed on your machine before anything else.

| Tool | What it's for | Install |
|---|---|---|
| **Git** | Version control | [git-scm.com](https://git-scm.com/) |
| **Docker** (with Compose v2) | Runs the entire stack — app, Postgres, Redis | [docs.docker.com/get-docker](https://docs.docker.com/get-docker/) |
| **just** | Task runner — wraps Docker/Compose/Alembic commands | [github.com/casey/just#installation](https://github.com/casey/just#installation) |

That's it for running the app. The Docker image handles Python, `uv`, and all dependencies internally.

**Optional (for running linting locally):**

| Tool | What it's for | Install |
|---|---|---|
| **uv** | Python package manager — installs and locks deps | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |
| **Python ≥ 3.11** | Required by `pyproject.toml` | Managed by `uv` or [python.org](https://www.python.org/) |

If you want to run `just lint` or `just fix` locally (outside Docker), you'll need a local Python environment:

```bash
uv sync          # creates .venv and installs all deps (including dev)
```

---

## Quick Start

From zero to running in ~2 minutes:

```bash
git clone git@github.com:emad-anwer/tem-platform.git
cd tem-platform

cp .env.example .env        # local defaults work out of the box

just up                      # build & start app, postgres, redis (detached)
just migrate                 # apply database migrations
```

Wait 10–15 seconds after `just up` for Postgres and Redis health checks to pass. The app container won't start until both are healthy.

**Verify it's working:**

```bash
# All-in-one health check
just health

# Or manually:
curl http://localhost:8000/healthz     # → {"status": "ok"}
curl http://localhost:8000/readyz      # → {"status": "ok"} (checks Postgres + Redis)
```

**Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)

### Development with hot reload

```bash
just dev         # uses `docker compose watch` — syncs code changes, rebuilds on pyproject.toml changes
```

>[!Note]
`just dev` runs in the foreground. Use `just up` if you prefer detached mode.

### Useful commands

Run `just` with no arguments to see everything available. The highlights:

| Command | What it does |
|---|---|
| `just up` | Start the stack (detached) |
| `just dev` | Start with file watching / hot reload |
| `just down` | Stop and remove containers |
| `just nuke` | Stop containers **and** delete volumes + images (fresh start) |
| `just logs` | Follow logs from all services |
| `just logs-app` | Follow app logs only |
| `just shell` | Open a bash shell inside the app container |
| `just db-shell` | Open a `psql` shell connected to the database |
| `just build` | Rebuild the app Docker image |
| `just health` | Check health of app, Postgres, and Redis |

---

## Environment Configuration

Settings are loaded by `pydantic-settings` from environment variables and the `.env` file (see `src/app/core/config.py`).

### Setup

```bash
cp .env.example .env
```

The `.env` file is gitignored. Never commit it.

### Variables

| Variable | Default in `.env.example` | Notes |
|---|---|---|
| `APP_NAME` | `tem-platform` | Used as the FastAPI title |
| `ENVIRONMENT` | `dev` | Set to `dev` to enable debug mode |
| `LOG_LEVEL` | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`, etc.) |
| `POSTGRES_USER` | `tem_user` | Used by both Postgres container and the app |
| `POSTGRES_PASSWORD` | `changeme` | **Change in production** |
| `POSTGRES_DB` | `tem_platform` | Database name |
| `DATABASE_URL` | `postgresql+asyncpg://tem_user:changeme@postgres:5432/tem_platform` | The async SQLAlchemy connection string. The hostname `postgres` resolves inside Docker Compose. |
| `REDIS_PASSWORD` | `changeme` | **Change in production** |
| `REDIS_URL` | `redis://:changeme@redis:6379/0` | The hostname `redis` resolves inside Docker Compose. |

The defaults in `.env.example` work for local development without modification. If you change `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB`, update `DATABASE_URL` to match.

### Additional settings (usually left at defaults)

These are read from environment variables but have sensible defaults in `config.py`:

- `REDIS_MAX_RETRIES` (default: `3`) — startup retry attempts
- `REDIS_RETRY_BASE_DELAY` (default: `1.0`) — seconds, with exponential backoff
- `REDIS_SOCKET_CONNECT_TIMEOUT` / `REDIS_SOCKET_TIMEOUT` (default: `5.0`)
- `REDIS_HEALTH_CACHE_TTL` (default: `5`) — seconds to cache health check results
- `REDIS_REQUIRED` (default: `false`) — set to `true` in production to fail startup if Redis is unreachable

---

## Database & Alembic

Migrations live in `migrations/versions/`. The Alembic configuration is in `alembic.ini` (which sets `script_location = migrations` and `prepend_sys_path = src`).

The initial migration (`20260826_0001_initial.py`) is an empty baseline — application tables are added as modules are built.

### Apply migrations

```bash
just migrate
```

This runs `alembic upgrade head` inside the app container.

### Create a new migration

```bash
just migration "add users table"
```

This runs `alembic revision --autogenerate -m "..."` inside the container. Autogenerate compares your SQLAlchemy models against the current database schema.

> **Important:** always review the generated migration file before applying it. Alembic's autogenerate cannot reliably detect renamed columns, changed server defaults, or constraint renames. Check the file in `migrations/versions/` and edit if needed.

### Roll back one migration

```bash
just downgrade
```

This runs `alembic downgrade -1` (one step back). You can also pass a specific revision:

```bash
just downgrade <revision>
```

### Check migration state

From inside the container:

```bash
just shell
alembic current     # shows the current revision
alembic history     # shows the full revision chain
```

---

## Running Tests

There are two categories of tests:

1. **Unit tests** — mock external dependencies, run fast, no Docker needed
2. **E2E tests** — hit real Postgres and Redis inside Docker, marked with `@pytest.mark.e2e`

### Run all tests (unit + e2e)

Requires the Docker stack to be running (`just up`):

```bash
just test
```

This runs `pytest` inside the app container where Postgres and Redis are reachable.

### Run unit tests only

```bash
just test-unit
```

This runs `pytest -m "not e2e"` — skips tests that need real database/Redis connections. Safe to run outside Docker too if you have a local Python environment.

>[!Note]
even unit tests require `DATABASE_URL` to be set (it's referenced at import time by `config.py`). The test files set a dummy fallback via `os.environ.setdefault(...)` so they don't fail outside Docker.

### Run a specific test file or test

```bash
just shell
pytest tests/core/test_health.py                    # one file
pytest tests/core/test_health.py::test_healthz_is_always_200   # one test
pytest -k "redis"                              # by keyword
```

### Test files

| File | Type | What it covers |
|---|---|---|
| `tests/core/test_health.py` | Unit | Health endpoints with mocked DB/Redis |
| `tests/core/test_redis.py` | Unit | RedisManager internals — pool construction, sticky failures, URL masking |
| `tests/integration/test_e2e.py` | E2E | Real lifespan, health checks, DB+Redis roundtrip against live services |
| `tests/integration/test_target_lab.py` | Mixed | Static config validation (unit) + live probes against lab services (e2e) |

> [!Note]
> `tests/` mirrors `src/app`: core tests live under `tests/core/`, module tests under
> `tests/modules/<name>/`, worker tests under `tests/worker/`, and live-service tests
> under `tests/integration/`. New tests should follow the same mirrored path.

---

## Linting / Formatting

The project uses [Ruff](https://docs.astral.sh/ruff/) for both linting and formatting. Configuration is in `pyproject.toml` (target: Python 3.11, line length: 88).

### Check for issues

```bash
just lint
```

Runs `ruff check .` and `ruff format --check .`.

### Auto-fix

```bash
just fix
```

Runs `ruff check --fix .` and `ruff format .`.

> [!Note]
`just lint` and `just fix` run on your **host machine** (not inside Docker), so you need `ruff` installed locally. If you set up your local env with `uv sync`, it's included in the dev dependencies.

---

## How to Add a New Module

The project follows a modular monolith layout. Each module lives under `src/app/modules/<name>/` and has a standard set of files. All four existing modules (`asm`, `brand`, `darkweb`, `intel`) use the same structure — they're currently scaffolded as empty files, ready to be filled in.

### 1. Create the module directory

```
src/app/modules/<your_module>/
├── __init__.py
├── models.py         # SQLAlchemy ORM models
├── schemas.py        # Pydantic request/response schemas
├── repository.py     # Database queries (takes a session, returns data)
├── service.py        # Business logic (calls repository, orchestrates)
├── route.py          # FastAPI APIRouter with endpoint definitions
└── api.py            # Public API surface (re-exports for other layers)
```

Create all files even if some start empty — it keeps the structure consistent.

### 2. Define your models

In `models.py`, define SQLAlchemy 2.0 mapped classes. The database engine and session factory are in `app.core.db`.

### 3. Create Pydantic schemas

In `schemas.py`, define request/response models. See `docs/api-conventions.md` for naming and envelope conventions.

### 4. Build the repository layer

In `repository.py`, write async functions that accept an `AsyncSession` and perform queries. Keep raw SQL/ORM logic here, not in the service.

### 5. Add business logic

In `service.py`, orchestrate between repositories. This is where validation, authorization checks, and cross-cutting logic go.

### 6. Define routes

In `route.py`, create a `router = APIRouter(prefix="/<your_module>", tags=["<your_module>"])` and define your endpoints.

### 7. Register the router

In `src/app/core/main.py`, import your router and add it:

```python
from app.modules.<your_module>.route import router as <your_module>_router

# inside create_app():
app.include_router(<your_module>_router)
```

### 8. Create a migration

If your module adds database tables:

```bash
just migrate                          # make sure you're at head first
just migration "add <module> tables"  # generates the migration
```

Review the generated file in `migrations/versions/`, then apply:

```bash
just migrate
```

### 9. Add tests

Create test files mirroring the source tree under `tests/`:
- `tests/modules/<module>/` for module unit tests (mock DB/Redis)
- `tests/core/` for shared core tests
- `tests/integration/` for tests needing live services — mark them with `@pytest.mark.e2e`

### The one rule

**A module never imports another module.** Modules depend only on `core`. If your module needs data from another module, it goes through an interface in `core` — never a direct import.

---

## Target Lab (Optional)

The `lab/` directory contains four pre-configured web servers used as scan targets for ASM development and testing. They run under a separate Docker Compose profile so they don't start by default.

```bash
just lab-up       # start lab services (auto-generates the TLS SAN cert first run)
just lab-down     # stop lab services
just lab-logs     # follow lab logs
just lab-certs    # (re)generate the lab-tls-san certificate; idempotent
```

> [!Note]
> `just lab-up` depends on `just lab-certs`, which generates the self-signed multi-SAN certificate
> for `lab-tls-san` when it's missing (e.g. on a fresh clone) — no manual steps needed. The
> certificate and key live in `lab/tls/certs/` and are gitignored. Requires **OpenSSL** on the host
> (already needed for the `openssl s_client` verification command in `docs/target-lab.md`).

| Target | Port | Description |
|---|---|---|
| `lab-nginx` | 8081 | Nginx on standard port |
| `lab-apache` | 8082 | Apache on standard port |
| `lab-nonstandard` | 8888 | Nginx on non-standard port |
| `lab-tls-san` | 8443 | Nginx with TLS + SAN certificate |

See [docs/target-lab.md](docs/target-lab.md) for full details.

---

## Troubleshooting

### Docker says "port already in use"

**Symptom:** `Bind for 0.0.0.0:8000 failed: port is already allocated`

**Fix:** Something else is using port 8000. Either stop it or change the port mapping in `compose.yaml`.

```bash
lsof -i :8000     # find what's using it
```

### App container keeps restarting

**Symptom:** `just logs-app` shows `Database connection check failed` or the app exits immediately.

**Cause:** Postgres isn't ready yet, or `DATABASE_URL` is wrong.

**Fix:** Wait for Postgres health check to pass (`just health`). If it still fails, check that `DATABASE_URL` in `.env` matches `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`.

### Redis connection warnings on startup

**Symptom:** Logs show `Redis not available after N attempts, running without cache/queue`.

**Cause:** Redis isn't reachable. By default (`REDIS_REQUIRED=false`) the app continues without Redis.

**Fix:** Check `just health`. Verify `REDIS_URL` and `REDIS_PASSWORD` in `.env` match the Redis container config.

### Migrations fail with "target database is not up to date"

**Symptom:** `just migration "..."` fails.

**Fix:** Run `just migrate` first to apply pending migrations, then try again.

### Stale data / want a clean slate

```bash
just nuke          # removes containers, volumes, and local images
just up
just migrate
```

This deletes all database data and Redis state.

### `just` command not found

**Fix:** Install just — see [Prerequisites](#prerequisites).

On macOS: `brew install just`. On Linux: `curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to /usr/local/bin`

### Tests fail outside Docker

**Symptom:** `pytest` fails with connection errors.

**Cause:** E2E tests need Postgres and Redis running inside Docker. Unit tests need `DATABASE_URL` set (even a dummy value).

**Fix:** Run tests inside Docker with `just test`, or run only unit tests with `just test-unit`.

### `ruff` / linting not found

**Symptom:** `just lint` says `ruff: command not found`.
Run `just` to see all available commands.

**Fix:** Lint commands run on the host, not in Docker. Set up a local env:

```bash
uv sync
source .venv/bin/activate
just lint
```


## Documentation

| Doc                                | What it is                                                        |
| ---------------------------------- | ----------------------------------------------------------------- |
| [pipeline.md](docs/pipeline.md)      | How the pipeline runs: request → worker → findings, adding a job, stuck scans, crt.sh outages |
| [ROADMAP.md](docs/ROADMAP.md)      | The 8-week plan — what gets built when, and why in that order     |
| [DECISIONS.md](docs/DECISIONS.md)  | Every architectural decision and the reasoning behind it          |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How we work: branches, PRs, review, definition of done            |
| `docs/adr/`                        | Architecture Decision Records                                     |
| `docs/api-conventions.md`          | Error envelope, pagination, naming — agreed by the team in week 1 |


## The one rule

**A module never imports another module.** Modules depend on `core`. When ASM needs data that
Threat Intelligence owns, it goes through an interface in `core` — never a direct import.

Everything else about the architecture is negotiable. This isn't.
