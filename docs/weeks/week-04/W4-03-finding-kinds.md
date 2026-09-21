# W4-03 · Finding kinds and a fingerprint that isn't about subdomains

**Owner:** Zyad · **Reviewer:** Arwa + mentor · **Effort:** 4h · **Depends on:** W4-01

🔑 The architectural spine of the week. W4-04, W4-07 and W4-08 all need this before they can write a
finding.

## What

Implement what ADR-0004 decided.

Today, in `core`:

- `discovery.py` has a private `_fingerprint(target_id, value)` that builds
  `f"subdomain|{target_id}|{value}"`
- `repository.py` writes `kind="subdomain"` as a literal in **two** places —
  `upsert_discovery` (line ~682) and `upsert_discovery_batch` (line ~767)
- `value_normalized` is copied straight from `item["value"]` in the batch path, with a comment
  saying callers must normalise first

All three are fine for one finding kind and wrong for four. Fix them:

- **A fingerprint function that lives in `core` and takes the kind as an argument.** Not
  `fingerprint_subdomain` and `fingerprint_port` — one function, parameterised, implementing the
  rule ADR-0004 wrote down. Where it lives matters: `modules/asm` and `modules/threat_intel` must
  both reach it without importing each other
- **A `FindingKind`** in whatever form ADR-0004 chose. If it is a Postgres enum or a `CHECK`, this
  task owns the migration
- **A write path that takes the kind from the caller.** `upsert_discovery_batch` becomes a generic
  finding upsert. Keep the properties W3-08 got right — `ON CONFLICT` on
  `(tenant_id, fingerprint)`, `first_seen_at` excluded from the SET clause, `times_seen`
  incremented, `details` merged rather than replaced, one commit for the batch
- **Normalisation that the repository enforces rather than documents.** A comment telling callers
  to normalise is the disciplinary version of the thing week 2 argued against. Four callers land
  this week; one of them will forget

Tests:

- The same input produces the same fingerprint in two processes (not just twice in one)
- Two kinds with the same `value` on the same target produce *different* fingerprints
- The same finding from two different sources produces *one* row
- `first_seen_at` does not move on re-upsert; `last_seen_at` and `times_seen` do
- A batch of mixed kinds writes correctly in one transaction
- An unnormalised value written through the repository comes back normalised

## Expected outcome

`grep -rn '"subdomain"' src/app/core/` returns nothing outside the ASM module and the enum
definition itself. Adding a fifth kind touches the enum and the caller — nothing in `repository.py`.

## Think about

This is a refactor of working, merged, tested code, which is a different job from writing it. The
risk is not that it breaks; the risk is that you generalise it into something nobody can read. Every
parameter you add has to be one that an actual caller this week actually needs.

**Arwa reviews this, and she wrote `discovery.py` in W3-07.** That is the point. She is the only
person who knows which of that file's behaviours were decisions and which were accidents — including
why the *source* is deliberately not part of the subdomain fingerprint. If your generalisation
quietly drops a property she chose, she will notice and nobody else will.

The test that this landed is knowledge check #6, and the mentor will ask it at the demo: *add a
fifth kind, `dns_record`. Name every file you have to touch.* Know your own answer before Thursday.

**This PR carries `needs-mentor-review`** — it changes the schema and a `core` contract.

## Search for

- sqlalchemy enum column migration add value
- postgres alter type add value transaction
- on conflict do update excluded partial
- deterministic hash sha256 stable across processes
- python strenum validation boundary
- refactor extract parameter generalize function
