# W1-04 · App factory, settings, health endpoints

**GitHub issue:** [#4](https://github.com/emad-anwer/tem-platform/issues/4)

**Owner:** Arwa · **Reviewer:** Tasneem · **Effort:** 3h · **Depends on:** #1

## What

- `create_app()` application factory
- Pydantic Settings reading configuration from the environment — **no hardcoded database URL**
- `GET /healthz` — liveness. Returns 200 if the process is alive. Touches nothing else
- `GET /readyz` — readiness. Checks the database connection and fails if it can't serve traffic

## Expected outcome

App boots. Stop Postgres: `/healthz` still returns 200, `/readyz` returns 503.

## In the PR description

Explain in two sentences why these are two separate endpoints and who consumes each. If you can't,
you haven't finished the task.

## Search for

- FastAPI application factory pattern
- pydantic-settings BaseSettings
- liveness vs readiness probe
- FastAPI lifespan events
