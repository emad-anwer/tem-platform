# Scanning Policy

## What the platform may scan

The platform connects only to hosts that appear in `SCAN_SCOPE_ALLOWLIST`
in the `.env` file (or the equivalent environment variable in production).

The allowlist is comma-separated. Each entry is one of:

- a hostname: `lab-nginx`, `example.com`
- an IP address: `203.0.113.10`
- a CIDR: `203.0.113.0/24`
- a loopback address with an explicit port: `127.0.0.1:8081`

The list is configured once per deployment by whoever runs the deployment,
not per-tenant and not per-scan. Per-tenant scope is a week-6 problem
(`src/app/core/scope.py` line 47).

The default value in `.env.example` is the lab:

```
SCAN_SCOPE_ALLOWLIST=lab-nginx,lab-apache,lab-nonstandard,lab-tls-san,target4.lab.local
```

This is implemented and enforced in `src/app/core/scope.py`.

---

## What is blocked unconditionally

Three address classes are blocked regardless of what appears in the allowlist.
No allowlist entry can override these.

| Blocked | Why |
|---|---|
| **Link-local** (`169.254.0.0/16`, `fe80::/10`) | Cloud metadata endpoints live here (`169.254.169.254`). Scanning them from a cloud VM would read instance credentials. |
| **Multicast** (`224.0.0.0/4`, `ff00::/8`) | Not a host; sending a TCP connect to a multicast address produces undefined and potentially disruptive results. |
| **Unspecified / reserved** | Addresses that cannot be legitimate scan targets by definition. |

Loopback (`127.0.0.0/8`, `::1`) is **not** unconditionally blocked, because
the lab is reachable on loopback from a laptop. However, loopback addresses
are only reachable through a **port-qualified** allowlist entry
(e.g. `127.0.0.1:8081`). A bare `127.0.0.1` does not grant loopback access.

RFC 1918 private addresses (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`)
are **not** unconditionally blocked. They can be allowlisted explicitly,
which is how the Compose network's container addresses work: `lab-nginx`
resolves to a `172.x.x.x` container address, and listing `lab-nginx` by name
is the explicit permission. An intern scanning their home router by adding
`192.168.1.0/24` to `SCAN_SCOPE_ALLOWLIST` would need approval before
that entry could reach the file.

---

## What an intern does when they think they need to scan something new

They ask. They do not add the entry themselves.

Adding a new target to `SCAN_SCOPE_ALLOWLIST` is a code change that goes
through a PR and review. The PR description must state:

1. What the target is.
2. Who owns it and has authorized scanning it.
3. Why the platform, rather than its owner, is doing the scanning.

If the target is a production system or a third-party host, the answer to
point 3 is almost certainly "there is no good reason" and the answer to the
question is no.

---

## The politeness budget

The scanner's outbound traffic rate is capped by a Redis-backed sliding-window
limiter in `src/app/core/rate_limit.py`. The shared budget is:

| Setting | Default | Env var |
|---|---|---|
| Admission rate | 5 requests / second | `SCAN_RATE_LIMIT_DEFAULT_PER_SECOND` |
| Maximum wait for a slot | 10 seconds | `SCAN_RATE_LIMIT_MAX_WAIT_SECONDS` |
| Per-host overrides | none | `SCAN_RATE_LIMIT_OVERRIDES` |

The budget is shared across every worker process connected to the same Redis
instance. It applies to TCP connections (`operation="tcp"`) and HTTP requests
(`operation="http"`) independently.

The budget exists because the scanner will eventually run on schedule against
real external targets. A scanner that fires 200 connections per second at a
target it does not own is an outage, not an assessment. Even on the lab,
running without a rate limit means a future change that accidentally doubles
the target list doubles the connection rate with no warning.

If you need a higher rate for a specific host (e.g. the lab during a load
test), set `SCAN_RATE_LIMIT_OVERRIDES={"lab-nginx": 50}` in `.env`. That is
a local-only change and does not affect what the platform is permitted to scan.
