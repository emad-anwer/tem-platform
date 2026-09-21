# W2-01 · CI pipeline: ruff and pytest on every PR

**GitHub issue:** [#31](https://github.com/emad-anwer/tem-platform/issues/31)

**Owner:** Islam · **Reviewer:** Zyad · **Effort:** 4h · **Depends on:** —

Dependency-free by design. If Sunday's huddle overruns, this is the work to pick up.

## What

A GitHub Actions workflow that runs on every pull request:

- `ruff check` and `ruff format --check`
- `alembic upgrade head` against a **Postgres service container**, not SQLite
- `pytest`
- `uv` cache, so the install step isn't the slow part
- `concurrency` with cancel-in-progress, so pushing twice doesn't queue two runs

**Hard constraint: the pipeline must not need Zitadel.** No IdP container, no network call to one.
If you find yourself adding a Zitadel service to CI, stop — W2-03 exists precisely so that tests
mint their own tokens. Say so on the PR rather than working around it.

## Expected outcome

Every PR shows a green tick or a red X within roughly three minutes, and the run tells you which
of the four steps failed without you opening the log.

Propose the check names that should be required before merge. The mentor enables branch protection
using them — right now anyone can merge anything, which is itself worth understanding.

## Think about

Three minutes is a budget, not a wish. A suite that takes fifteen is a suite people learn to ignore
while it runs, and the point of a gate is that it blocks. What did you do to stay inside it, and
what would you cut first if week 5 pushes you over?

## Search for

- github actions service containers postgres health check
- astral-sh/setup-uv cache
- github actions concurrency cancel-in-progress
- required status checks branch protection
- ruff check vs ruff format --check
