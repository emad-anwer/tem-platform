# W1-11 · Test scaffolding and first tests

**GitHub issue:** [#11](https://github.com/emad-anwer/tem-platform/issues/11)

**Owner:** Tasneem · **Reviewer:** Arwa · **Effort:** 3h · **Depends on:** #7

## What

- pytest, pytest-asyncio, httpx `AsyncClient` against the app
- `conftest.py` with an app fixture and a database fixture using **transactional rollback per
  test**, so tests don't leak state into each other
- Four tests on the tenant endpoints: create succeeds, duplicate slug returns 409, get by ID,
  list returns the created tenant

## Expected outcome

`just test` runs green from a clean state, repeatedly, in any order.

## The real deliverable

The four tests matter less than the **scaffolding**. Week 2 adds auth tests, week 3 adds job
tests, and every one of them builds on the fixtures you write here. Make them clean.

Tests that pass only when run in a particular order are worse than no tests. Verify by running
them twice in a row.

## Search for

- pytest-asyncio
- httpx ASGITransport AsyncClient
- pytest fixture transactional rollback
- SQLAlchemy nested transaction SAVEPOINT
