# W1-06 · Tenant model and repository

**GitHub issue:** [#6](https://github.com/emad-anwer/tem-platform/issues/6)

**Owner:** Zyad · **Reviewer:** Arwa · **Effort:** 4h · **Depends on:** #5

## What

SQLAlchemy 2.0 `Tenant` model:

| Field | Notes |
|---|---|
| `id` | UUID primary key |
| `name` | human-readable display name |
| `slug` | URL-safe, **unique constraint** |
| `created_at` | UTC, server default |
| `is_active` | boolean, default true |

Plus the migration, and a `TenantRepository` with `create`, `get_by_id`, `get_by_slug`, `list`.

## Expected outcome

Model and migration merged. Repository is the only place that touches the database — the service
layer above it never writes SQL.

## Think about

Why does a tenant have both a UUID and a slug? One is a surrogate key, one is a natural key. Be
ready to say which is which and why you'd want both.

## Search for

- SQLAlchemy 2.0 Mapped mapped_column
- surrogate key vs natural key
- PostgreSQL UUID primary key
- repository pattern Python
