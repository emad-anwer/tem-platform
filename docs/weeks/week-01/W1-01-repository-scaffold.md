# W1-01 · Repository scaffold and module layout

**GitHub issue:** [#1](https://github.com/emad-anwer/tem-platform/issues/1)

**Owner:** Zyad · **Reviewer:** Islam · **Effort:** 4h · **Depends on:** nothing

Blocks almost every other week 1 task — ship this first thing Sunday.

## What

Create the package structure and tooling baseline.

```
app/
  core/            # shared infrastructure — config, db, logging, errors
  modules/
    asm/           api.py service.py repository.py models.py schemas.py
    intel/         (same)
    darkweb/       (same)
    brand/         (same)
tests/
docs/
```

Each module gets the five empty files even though they're unused, so the intended shape is
visible from day one.

Also: `pyproject.toml` managed with `uv`, ruff configured for both lint and format,
`.gitignore`, `.env.example`.

## Expected outcome

- `uv sync` works on all four machines and produces identical environments
- `ruff check .` and `ruff format --check .` pass clean
- The layout matches what ADR-0001 (#12) will describe

## Why `uv`

Current Python standard, resolves in seconds rather than minutes, and its lockfile makes
"works on my machine" reproducible. Not a learning goal — just the fastest route to four
identical environments.

## Search for

- `uv` Python package manager
- `ruff` configuration in pyproject.toml
- Python src layout vs flat layout
- modular monolith folder structure
