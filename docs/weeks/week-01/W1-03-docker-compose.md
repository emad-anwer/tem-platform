# W1-03 · Docker Compose: Postgres, Redis, app

**GitHub issue:** [#3](https://github.com/emad-anwer/tem-platform/issues/3)

**Owner:** Islam · **Reviewer:** Zyad · **Effort:** 4h · **Depends on:** #1

## What

- Multi-stage `Dockerfile` — build layer and a slim runtime layer
- `compose.yaml` with Postgres, Redis, and the app
- **Healthchecks** on Postgres and Redis, with `depends_on: { condition: service_healthy }`
- Named volumes so data survives `down`
- Hot reload for local development
- A `justfile` with: `up`, `down`, `logs`, `migrate`, `test`, `lint`

## Expected outcome

From a clean clone: `cp .env.example .env && just up` gives a running stack.

**Verified on all four machines** — not just the author's. Post confirmation in the PR.

## Watch out for

`depends_on: condition: service_healthy` makes the app *wait*, but it does not make the app
*resilient*. Ask yourself what happens when Postgres restarts while the app is already running.
You'll be asked this in the knowledge check.

## Search for

- Docker Compose healthcheck
- depends_on condition service_healthy
- multi-stage Dockerfile Python
- Docker named volumes
- justfile / just command runner
