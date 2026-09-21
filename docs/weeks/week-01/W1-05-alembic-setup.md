# W1-05 · Alembic setup and initial migration

**GitHub issue:** [#5](https://github.com/emad-anwer/tem-platform/issues/5)

**Owner:** Tasneem · **Reviewer:** Arwa · **Effort:** 3h · **Depends on:** #1, #4

Blocks #6, which blocks #7 — a three-person chain. If this slips, two people stall.

## What

- `alembic init`, with `env.py` wired to the async engine and to Settings — **not** a hardcoded URL
- First revision (can be empty; the tenant table arrives in #6)
- `just migrate` runs upgrades inside the container
- Document the downgrade path in the PR

## Expected outcome

- `just migrate` works from a clean database
- `alembic downgrade -1` runs successfully and is documented

## Read first

The Alembic docs on **what `--autogenerate` does and does not detect**. It silently misses server
defaults, constraint renames, and some type changes. You will run this command fifty times over
eight weeks — knowing its blind spots now prevents a data-loss migration in week 5.

## Search for

- Alembic autogenerate limitations
- Alembic env.py async engine
- alembic downgrade
- async_engine_from_config
