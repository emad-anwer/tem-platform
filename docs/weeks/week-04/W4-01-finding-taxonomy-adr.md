# W4-01 · ADR-0004: finding kinds, fingerprints, and what "changed" means

**Owner:** Tasneem · **Reviewer:** all four + mentor · **Effort:** 2h + 45m huddle · **Depends on:** —

🔑 Sunday. Three people stall Monday morning if this does not merge.

## What

Run a 45-minute huddle, then write ADR-0004. The huddle has three questions and they are all really
the same question: **what is a finding?**

Week 3 answered it for exactly one case. `_fingerprint` in `discovery.py` builds the string
`f"subdomain|{target_id}|{value}"`. `FindingRepository.upsert_discovery` and
`upsert_discovery_batch` both write `kind="subdomain"` as a literal — in `core`, the spine all four
modules plug into. This week adds `open_port`, `http_service` and `tls_certificate`; week 5 adds a
threat-intel kind. Four people are about to need an answer at the same time.

**Question 1 — is `kind` an enum or free text?**

Today `kind`, `status` and `severity` are all `Text` columns. Options, and each costs something:

- A **Postgres enum** — the database rejects a typo, and adding a value needs a migration
- A **`CHECK` constraint** — same protection, also needs a migration, easier to read
- A **Python `StrEnum` validated at the boundary** — no migration ever, and the database will
  happily hold a kind the code has never heard of
- **Leave it `Text`** — costs nothing today and costs a debugging session in week 6

Pick one. Write down what it costs. "We'll decide later" is not on the list — four kinds land this
week whether or not the decision does.

**Question 2 — where does the fingerprint live, and what goes into it?**

The identity of a subdomain finding is `(target, hostname)`. An `open_port` finding's is
`(target, host, port)` — and arguably protocol. A `tls_certificate` finding's is either the
certificate's own SHA-256, or `(host, port)` with the certificate as *state* that can change.

Those are different answers, and the difference matters: if the certificate is identity, renewing
it resolves the old finding and creates a new one every 90 days. If it is state, the finding
persists and its `details` change. Both are defensible. Decide.

Then decide the **rule**, not the four cases:

- Is `kind` itself part of the hash input, or only part of the unique constraint?
- Is `tenant_id` in the hash? (Today it is not — the unique constraint is
  `(tenant_id, fingerprint)`. Is that deliberate?)
- What happens when two *different* sources find the same thing? W3-07 already decided the source is
  not part of identity for subdomains. Does that generalise?
- Where does the function live so that `modules/asm` and `modules/threat_intel` both reach it
  without importing each other?

**Question 2b — does `src/app/modules/asm/` finally get used?**

Check it before the huddle. `models.py`, `repository.py`, `service.py`, `route.py`, `schemas.py`,
`api.py` — **six empty files**, scaffolded in week 1 and never written to. All four module packages
look like that. Every line of code the platform has, including `core/discovery.py`, which is ASM
work by any reading, lives in `core`.

That was fine while there was one module. This week adds port scanning, HTTP probing and TLS
parsing, which belong to ASM and to nothing else. So decide, once, for everybody:

- What is the test for "this belongs in `core`" versus "this belongs in `modules/asm`"? A rule, not
  a vibe. "Every module needs it" is a start — apply it to the scanner, the scope guard, the rate
  limiter and change detection and see if it still holds for all four.
- Does `core/discovery.py` move to `modules/asm`? If yes, this week, while it is 324 lines and one
  caller. If no, say why in the ADR — "it was already there" is not why.
- If the answer turns out to be "almost everything stays in `core`", then say that out loud and
  ask what the four empty packages are *for*. A module layout nobody uses is worse than no module
  layout, because it looks like a boundary and enforces nothing.

**Question 3 — what is a change?**

Given run N and run N+1, every finding is one of: `new`, `reappeared`, `resolved`, `unchanged`. Is
there a fifth — `mutated`?

Concretely: `lab-nginx` returned `Server: nginx/1.25.4` last run and `nginx/1.27.0` this run. Same
host, same port, same service, different version. Is that the same finding with changed details, or
a new finding? A security product probably wants to *highlight* it either way, so the real question
is where it shows up: in the diff, or in the finding's history.

Decide, and decide whether `status` needs a value it does not have today.

**A fourth thing, five minutes, not a whole question.** `TargetKind` has `domain`, `ipv4`, `ipv6`,
`cidr`, `keyword`, `brand_name`, `app_store_url` — and no bare hostname. The worker reaches the lab
containers as `lab-nginx` on the compose network, which is a single-label name. Either `domain`
accepts it, or there is a new kind. Decide in the huddle so W4-02 and W4-04 don't each invent an
answer on Monday.

**Deliverable:** `docs/adr/0004-finding-taxonomy.md`, in the same shape as ADR-0003. Context,
decision, alternatives considered, consequences. Name the three decisions explicitly enough that
W4-03 is an implementation task and not a second design discussion.

## Expected outcome

ADR-0004 merged Sunday. W4-02 and W4-03 can both start Monday morning without asking anyone
anything.

## Think about

You are writing an ADR that modifies code Islam designed (ADR-0003) and Zyad implemented (W3-02,
W3-08). That is deliberate. Your job in the huddle is not to have the best answer — it is to make
sure the two people who own the current design have to *defend* it rather than restate it.

The failure mode to watch for: all four of you agree in ten minutes. If that happens, you have not
understood question 1. Ask what breaks in week 5 when threat intel adds a kind, and re-open it.

One more, worth five minutes at the end: the permission matrix in `core/auth/permissions.py` has
`TARGET_CREATE` and `SCAN_START` but **no read permissions at all**. Every read endpoint is
authenticated but ungated. That is correct today — every role should be able to read. W4-08 adds a
`/changes` endpoint and week 6 adds alerts. Is it still correct then? You do not have to fix it;
you have to notice it.

## Search for

- architecture decision record template consequences
- polymorphic identity single table inheritance
- postgres enum vs check constraint vs application validation
- content addressable identity deterministic hash
- security finding deduplication taxonomy
- defect lifecycle new reopened resolved
