# ADR-0004: Finding Kinds, Fingerprints, and What "Changed" Means

**Date:** 2026-09-23
**Status:** accepted
**Owners:** Tasneem (ADR) · **Reviewers:** all four + mentor
**Gates:** W4-02, W4-03, W4-04 start from this.
**Applies to:** every `Finding`-producing job added in weeks 4-7 (ASM ports/HTTP/TLS this week,
threat-intel next), and `Target` creation for internal/lab-only hosts.

## Context

ADR-0003 built one pipeline -- `Target`, `ScanRun`, `Finding` -- for four eventual producers, and
answered the identity question for exactly one case: a subdomain finding's identity is
`(kind="subdomain", target_id, hostname_normalized)`, hashed to a `fingerprint` under
`UNIQUE (tenant_id, fingerprint)`. `core/discovery.py` implements that as a hardcoded string,
`f"subdomain|{target_id}|{value}"`, and `FindingRepository.upsert_discovery` writes
`kind="subdomain"` as a literal.

Week 4 adds three more finding kinds -- `open_port`, `http_service`, `tls_certificate` --
against the same `target_id`s subdomain discovery already writes to. Week 5 adds a threat-intel
kind. This ADR settles:

1. How `Finding.kind` (and `Target.kind`) should be enforced.
2. What makes each new kind of finding "the same finding" across scan runs -- generalizing
   ADR-0003 Section 6's fingerprint rule beyond the one case it was written for.
3. Whether `core/discovery.py` -- subdomain-specific scanning logic sitting in `core` because it
   was the only module when it was written -- belongs in `modules/asm/`, and what rule decides
   that going forward.
4. What "changed" means once a finding can be re-observed with different details (a service
   version bump, a certificate renewal), and what that does and doesn't give us for free.
5. That `TargetKind` gains a bare-hostname value, since the worker reaches lab containers by
   single-label compose-network names (e.g. `lab-nginx`), which `_is_domain`'s dot requirement
   rejects today.

## Decision

### 1. `Finding.kind` (and `Target.kind`) stay `Text`, validated by a Python `StrEnum` at the application boundary

ADR-0003 Section 2 already made this call for `Target.kind` explicitly ("a new kind in week 6
must not require a constraint migration") and implied it for `Finding.kind` ("open set like
`Target.kind`"). We're keeping that, and giving `Finding.kind` the same shape a value already
in this codebase uses: `TenantProvisioningAttempt.status` is `Mapped[ProvisioningStatus]` over a
plain string column, where `ProvisioningStatus` is a `StrEnum`.

```python
class FindingKind(StrEnum):
    SUBDOMAIN = "subdomain"
    OPEN_PORT = "open_port"
    HTTP_SERVICE = "http_service"
    TLS_CERTIFICATE = "tls_certificate"
    # week 5 adds a member here, not a migration


kind: Mapped[FindingKind] = mapped_column(Text, nullable=False)  # column unchanged
```

**What this is, precisely:** application-level validation, not database enforcement. Pydantic
rejects an unknown `kind` at the API boundary (422), and typing the repository methods as
`kind: FindingKind` rather than `kind: str` catches mistakes in code review and mypy. The
`Text` column itself has no constraint -- a raw SQL write, a bad migration, or code that
bypasses the repository can still put an arbitrary string in that column, same as
`Target.kind` today. We're accepting that, same as ADR-0003 did, because the alternative has a
real recurring cost: Postgres won't let you add an enum value and use it in the same
transaction that added it, which in practice means two migrations instead of one every time a
kind is added. With four kinds landing this week and a fifth next week, that's not worth the
extra DB-level guarantee.

### 2. Fingerprint: one shared function in `core`, one identity tuple per kind

For every kind, `value_normalized` is just the canonical string form of that kind's identity
tuple -- the thing that gets hashed. It's not a separate design choice per kind; it's how the
tuple in the table below turns into a string.

```python
# core/fingerprint.py
def compute_fingerprint(
    kind: FindingKind, target_id: UUID, value_normalized: str
) -> str:
    identity = f"{kind}|{target_id}|{value_normalized}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
```

This lives in `core`, not `modules/asm`, because both `modules/asm` and the future
`modules/threat_intel` need it and shouldn't import each other (ADR-0001's `modules -> core,
never modules -> modules`). Each module computes its own `value_normalized`; the shared part is
just the hash.

**Included in the hash:** `kind`, `target_id`, the normalized identity value -- unchanged from
ADR-0003, generalized to every kind. **Excluded:** `source` (ADR-0003 already ruled this out for
subdomains -- DNS and crt.sh finding the same host is one finding, and the same logic applies to
every kind: which scanner observed something is provenance, not identity) and `tenant_id` (see
below).

**Per-kind identity:**

| Kind | Identity | `value_normalized` | Mutable -- lives in `details` |
|---|---|---|---|
| `subdomain` | `(target_id, hostname)` | lowercase, no trailing dot, IDNA | resolved IPs, record types |
| `open_port` | `(target_id, host, port, protocol)` | `f"{host}:{port}/{protocol}"` | banner, grabbed service name |
| `http_service` | `(target_id, host, port, scheme)` | `f"{scheme}://{host}:{port}"` | `Server` header, version |
| `tls_certificate` | `(target_id, host, port)` | `f"{host}:{port}"` | certificate hash, issuer, SANs, validity dates |

`open_port` includes protocol -- TCP/53 and UDP/53 are different services and shouldn't merge
just because the port number matches. `tls_certificate` identity is the endpoint, not the
certificate itself: a renewal changes what's in `details`, not what's being identified, so it's
a change to an existing finding rather than a resolve-and-recreate every ~90 days. This was the
one call in here that's genuinely arguable either way; see Alternatives Considered for the
certificate-hash-as-identity option and why we didn't take it.

Because `value_normalized` is part of identity, it never changes for a finding that continues to
exist -- if an identity-defining field changes, that's a different fingerprint and a new
finding, not the same finding mutating. Everything that's expected to vary run over run belongs
in `details`, not in the identity tuple.

**`tenant_id` isn't in the hash.** `target_id` is a globally unique UUID and every `Target`
belongs to exactly one tenant, so `target_id` already disambiguates tenants without needing to
say so. `UNIQUE (tenant_id, fingerprint)` exists to match the compound-key shape the rest of the
schema uses and to keep `tenant_id` as the leading, indexed column every tenant-scoped query
already filters on -- a query-shape choice, not a collision-prevention one. Unchanged from
ADR-0003.

**`upsert_discovery` generalizes** to take `kind`, `value`, `value_normalized`, and `details`
instead of hardcoding `kind="subdomain"` and an empty `details`. Its `ON CONFLICT` clause needs
to actually write `severity`, `raw_severity`, and `details`, which ADR-0003 Section 6 specified
and the current code doesn't do:

```sql
ON CONFLICT (tenant_id, fingerprint) DO UPDATE SET
    last_seen_at     = EXCLUDED.last_seen_at,
    last_seen_run_id = EXCLUDED.last_seen_run_id,
    times_seen       = findings.times_seen + 1,
    status           = 'active',
    severity         = EXCLUDED.severity,
    raw_severity     = EXCLUDED.raw_severity,
    details          = findings.details || EXCLUDED.details,
    updated_at       = now()
    -- first_seen_at deliberately excluded, unchanged
```

Worth being precise about what `details || EXCLUDED.details` does: it's a shallow JSONB merge
that produces the *current* state of the finding. It overwrites old keys with new values and
keeps keys the new observation didn't mention -- it does not keep a record of what a key used
to be. That's a real gap for the "what changed" question below, not something this merge
already solves.

Today's implementation skips this SET clause entirely, so `details` never changes after first
insert. Fixing that is a prerequisite for anything in Decision 4 to work, and ships in W4-03
with the same priority as the fix below, not as later polish.

**`resolve_missing_discoveries` becomes kind-scoped.** Its `WHERE` clause gains
`Finding.kind.in_(kinds)`, and every caller passes the kind(s) it's authoritative for. Without
this, a target with both `subdomain` and `open_port` findings would have its `open_port`
findings wrongly resolved by a subdomain-only run, whose `seen_fingerprints` by construction
never contains an `open_port` fingerprint. This is a correctness fix, needed before W4-03 can
safely add a second kind under one target.

### 3. `core/discovery.py` moves to `modules/asm/`

**The rule:** something belongs in `core` if it's a contract every module has to satisfy
identically. It belongs in `modules/<name>` if it's one module's particular implementation of
that contract, or specific to how only that module works.

| Concept | Placement | Why |
|---|---|---|
| Scanner logic (DNS, crt.sh, port/HTTP/TLS probes) | `modules/asm` | Concrete `ScanSource` implementations; nothing another module would reuse |
| Fingerprint generation | `core` | The one shared contract every producer needs |
| Scope guard (`_belongs_to_domain`) | `modules/asm` | Subdomain-specific suffix match today; could generalize later if a second module needs it |
| Outbound timeouts/backoff | `core` (already there: `core/jobs/timeouts.py`) | Reused by every outbound call regardless of module |
| Per-scan concurrency tuning (`DEFAULT_DNS_CONCURRENCY`) | `modules/asm` | Calibrated to one scan type |
| Upsert conflict handling, `resolve_missing_discoveries` | `core` | Operates the same way regardless of kind |
| `FindingKind`, fingerprint function | `core` | Every module contributes to one shared taxonomy |

`core/discovery.py` moves this week. Everything in it -- `DNSSource`,
`CertificateTransparencySource`, `discover_domain`, the job registration -- is a particular ASM
implementation by the same logic that puts the new port/HTTP/TLS scanners in `modules/asm`. It's
324 lines with one caller, which is the cheapest this move will ever be, and three siblings are
about to land in the same conceptual space. "It was already there" isn't a placement rule.

**On the rest of the `modules/asm/` scaffold:** `modules/asm/discovery.py` (the moved file,
extended with the new scanners and their job registrations) gets real content this week.
`modules/asm/models.py` and `modules/asm/repository.py` don't, because `Target`, `ScanRun`, and
`Finding` stay in `core` and ASM doesn't own any tables. That's not a reason to delete them right
now -- it's fine to leave them empty and remove them later, once someone's checked nothing
imports them, if ASM never ends up needing module-owned persistence. `route.py`, `api.py`, and
`schemas.py` stay as they are too; ASM has no API surface beyond the shared
`/api/v1/findings`/`/api/v1/scan_runs` endpoints today, but that could change sooner than a new
table would be needed. None of this is an architectural requirement this ADR is imposing --
it's just naming what has content and what doesn't right now.

### 4. Persisted status stays `active`/`resolved`; `new`/`reappeared`/`unchanged`/`mutated` are computed at write time, not stored, and are not the same thing as a change history

Three separate things: **identity** (Decision 2, the fingerprint), **persisted status** (a
column on the row), and **run-to-run change classification** (a label describing what happened
between two observations of the same finding).

**Status stays two-valued:** `active` / `resolved`, unchanged from ADR-0003. This is not being
expanded to cover `new`/`mutated`/etc. Several vulnerability-scanning tools follow a similar
shape at the storage layer -- a small persisted open/closed state, with richer labels like "new"
or "reopened" shown at read time rather than stored as a permanent status -- though we haven't
verified that against any specific vendor's documentation here, so take it as a supporting
pattern rather than a cited fact. The concrete reason we're keeping it small is that expanding
`status` would break every existing `status == "active"` filter in this codebase, including
`resolve_missing_discoveries`.

**The classifications, defined precisely.** Because a fingerprint match on `ON CONFLICT` means
identity already matched, none of these are about identity -- they're entirely about comparing
the incoming observation to the row's state immediately before this write:

- `new`: no existing row for this fingerprint. (Already available today via `upsert_discovery`'s
  `xmax = 0` / `inserted` return value.)
- `reappeared`: a row exists with `status = resolved`; this run saw it again.
- `unchanged`: a row exists with `status = active`, seen again, and the incoming `details` match
  what's stored.
- `mutated`: a row exists with `status = active`, seen again, and the incoming `details` don't
  match what's stored.
- `resolved`: handled separately by kind-scoped `resolve_missing_discoveries`.

The `lab-nginx: nginx/1.25.4 -> nginx/1.27.0` example is the same finding, classified `mutated`.
`http_service` identity is `(target_id, host, port, scheme)`; the version string isn't part of
that, so a version bump can't change identity -- it only changes `details`.

**What this does and doesn't give us.** Computing these classifications at write time is enough
to answer "what happened in this run" -- for example, feeding `ScanRun.new_findings_count`, or a
`mutated_count` alongside it. It is not enough, on its own, to answer "what has changed for this
finding over time." The merged `details` column holds only the current state; once a value is
overwritten by the merge, its previous value isn't retrievable from the `Finding` row anymore.
If W4-08's `/changes` endpoint needs to show a history of past change events rather than just
"what changed in the most recent run," that requires persisting those events somewhere -- a
change/event log, most likely -- which this ADR doesn't design and isn't assuming already
exists. That's real, undecided work for W4-08, not something to assume falls out of the upsert
for free.

### 5. `TargetKind` gains a `hostname` value; `domain` is not loosened

A new `TargetKind.HOSTNAME` value covers single-label, non-publicly-resolvable names like
`lab-nginx`, instead of loosening `domain` to accept them. `domain` targets are
subdomain-*enumeration* roots -- `discover_domain`'s CT-log query and `_belongs_to_domain` both
assume a multi-label public domain with children to discover. `hostname` targets have no
children to enumerate; they're scanned directly by the new port/HTTP/TLS scanners. This is one
new open-enum value, no DDL, same pattern ADR-0003 Section 2 already established for
`TargetKind`. (See the caveat in Context -- confirm against the real validator before
implementing.)

## Consequences

**Positive:** `Finding.kind` gets a real application-level type instead of a bare string, for
this week's four kinds and next week's fifth, with no migration. The fingerprint rule
generalizes into one shared function instead of a hardcoded literal per kind.
`resolve_missing_discoveries` stops being a latent cross-kind bug. `modules/asm/` gets real
content instead of six empty files next to a fully-populated `core/discovery.py`. `mutated`
gives us a real way to say "this changed" without adding a new persisted status or breaking
`active`/`resolved` filtering.

**Negative:** the upsert's `SET` clause grows (details merge, severity refresh) -- more logic in
a hot path, and it's a correctness fix rather than a nice-to-have, so it can't be deferred past
W4-03. `tls_certificate` identity-as-endpoint means a certificate's own history has to live
somewhere other than the finding row's current state. Moving `core/discovery.py` touches its one
existing caller and needs re-testing in an already busy week. And, worth stating plainly since it
almost got assumed away: this ADR gives us derived new/reappeared/unchanged/mutated for the most
recent run, but not a stored history of past changes -- if `/changes` needs the latter, that's
separate design work, not a byproduct of what's decided here.
