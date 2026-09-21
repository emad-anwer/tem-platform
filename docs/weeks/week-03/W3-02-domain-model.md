# W3-02 · Domain model: Target, ScanRun, Finding

**GitHub issue:** [#67](https://github.com/emad-anwer/tem-platform/issues/67)

**Owner:** Zyad · **Reviewer:** Arwa + mentor · **Effort:** 5h · **Depends on:** #66

🔑 `needs-mentor-review`. This is the schema every module writes into for the rest of the programme,
and the one thing this week that is genuinely expensive to change in week 6.

## What

Turn ADR-0003 into three tables and one migration.

- `Target`, `ScanRun` and `Finding` in **`src/app/core/`** — not in `modules/asm`. They are platform
  concepts; ASM is the first consumer
- All three inherit **`TenantOwnedMixin`**, which already gives you an indexed `tenant_id` foreign
  key with `ondelete="CASCADE"`. Don't hand-roll the column
- One Alembic migration in **`migrations/versions/`**, named with the same date prefix as its
  neighbours. While you are in there, delete the orphaned `alembic/` directory —
  [#54](https://github.com/emad-anwer/tem-platform/issues/54) has been open since week 2 and this is
  the task that touches migrations anyway
- A repository per model, subclassing `TenantScopedRepository`
- Indexes that match how things will actually be read: findings by target, findings by run, runs by
  target, and whatever the fingerprint from ADR-0003 needs to be unique on

**`TenantScopedRepository` leaves `_cursor_columns`, `_encode_cursor` and `_decode_cursor` as
`NotImplementedError`.** Every repository you add must implement them, and the columns you pick have
to be stable and unique enough to page over without skipping or repeating rows.

Tests: the tenant scoping actually holds, the cascade actually cascades, cursor pagination returns
every row exactly once across pages.

## Expected outcome

`just migrate` creates three tables. A repository constructed with one tenant's context cannot see
another tenant's rows, and there is a test that proves it rather than a comment that claims it.

## Think about

Two things, and the second is the interesting one.

**Where the module-specific detail lives.** A subdomain finding has a hostname and an IP. A leaked
credential has an email address and a breach date. If both are columns on `findings`, the table
grows a column per module and most rows are null. If both are a JSONB blob, you can't index or alert
on them. ADR-0003 chose something — implement that, and if implementing it reveals the choice was
wrong, say so in the PR rather than quietly picking differently.

**`TenantScopedRepository.create()` commits on every call.** Look at it. Then think about W3-07,
which will discover four hundred subdomains in one job. Four hundred commits, four hundred round
trips, and no way to roll the scan back as a unit. **W3-13 fixes it** — your job here is to build
the models so that a batched write is possible at all, and to say in your PR what you think the
transaction boundary should be. You are the person best placed to have an opinion.

## Search for

- sqlalchemy 2.0 declarative mapped_column typing
- alembic autogenerate limitations
- postgres partial index unique constraint
- keyset pagination stable sort tiebreaker
- sqlalchemy relationship lazy loading async pitfalls
- database index selectivity composite index column order
