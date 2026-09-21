# BUG-01 · `core` hardcodes `"subdomain"` in three places

**Severity:** medium (design debt, blocks W4-04/06/07) · **Found:** week-3 review ·
**Closed by:** [W4-03](W4-03-finding-kinds.md) · **Owner:** Zyad, as part of W4-03 ·
**Effort:** included in W4-03

## What is wrong

Three lines in `core` assume every finding is a subdomain:

```
src/app/core/repository.py:682    kind="subdomain",
src/app/core/repository.py:767    "kind": "subdomain",
src/app/core/discovery.py:323     identity = f"subdomain|{target_id}|{value}"
```

`core` is supposed to hold what every module shares. A subdomain is an ASM concept. So the shared
layer currently knows about one module's one finding type, and the fingerprint — the value the whole
dedup story rests on — has that assumption baked into its input string.

`repository.py:769` also has a comment noting that callers pass already-normalised hostnames, so
`value_normalized` is set to `item["value"]` unchanged. That is true today because `discovery.py` is
the only caller. It stops being true the moment W4-04 writes an open port.

## Why it matters this week

W4-04 (ports), W4-06 (HTTP services) and W4-07 (TLS certs) each need to write a finding that is not
a subdomain. If this is still hardcoded on Tuesday morning, three people each invent their own way
around it in three branches, and the merge is where you find out they disagree about what a
fingerprint is.

This is the reason W4-01 happens on Sunday and W4-03 on Monday.

## Not a defect in what shipped

Week 3 was asked for one finding kind and delivered one finding kind, with a deterministic
fingerprint and a working upsert. This is what "generalise when the second case arrives" looks like
when the second case arrives. Worth saying out loud in review so it doesn't read as a reprimand.

## Verification

After W4-03 merges: no occurrence of the literal `subdomain` anywhere under `src/app/core/` outside
a finding-kind enum definition.
