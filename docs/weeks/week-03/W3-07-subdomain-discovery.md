# W3-07 · Subdomain discovery: DNS and crt.sh behind a source interface

**GitHub issue:** [#72](https://github.com/emad-anwer/tem-platform/issues/72)

**Owner:** Arwa · **Reviewer:** Zyad · **Effort:** 5h · **Depends on:** #70, #71

The week's payoff, and the first code in this repository that does something a customer would
actually pay for.

## What

Given a domain target, find hostnames that belong to it.

- **DNS resolution**, async. A, AAAA, CNAME, and whatever else earns its place. Use dnspython's
  asyncio resolver — the blocking one stalls every other job sharing the worker's event loop
- **crt.sh**, the certificate transparency log. Every publicly trusted certificate ever issued for a
  domain is in a public log, including the ones for hosts nobody meant to publish. Query it over
  plain HTTPS with `httpx`. It is already in the tree, but under `[dependency-groups] dev` only —
  nothing has needed an HTTP client at runtime before this task, so promoting it to a runtime
  dependency is step one. No key, no account, no registration
- **A source interface** both implement. `DECISIONS.md` §5 is explicit: a source that is down
  returns **fewer results, not an exception**. crt.sh is free and regularly unavailable, and no demo
  may depend on a third party being up. Record in the `ScanRun` which sources ran and which degraded,
  so "zero findings" and "crt.sh was down" are distinguishable
- Deduplicate and normalise across sources: case, trailing dots, wildcards (`*.example.com` is not a
  host), out-of-scope results. crt.sh will return names for domains you did not ask about
- Persist findings via W3-02's repository. If W3-08 has landed, use its fingerprint; if not, leave
  the seam and let it fill in
- Politeness: a timeout on every call, a cap on results, and no unbounded recursion into discovered
  hostnames

**Tests never touch the network.** `respx` is already a dev dependency — record real crt.sh
responses once, as fixtures, and test against those. Include a fixture for a 502 and one for a
timeout, because those are the paths that matter.

Only scan domains we are authorised to scan. Nothing in this task probes a host, opens a port or
sends a single packet to infrastructure that isn't ours — this is passive discovery from public
records and public DNS. Keep it that way.

## Expected outcome

A scan of a real domain returns real subdomains. The full test suite proves it with the network
unplugged, and crt.sh returning 502 produces a successful run with fewer findings and a note saying
so.

## Think about

**Certificate transparency finds what DNS enumeration cannot.** DNS only answers questions you
already know to ask — you can't resolve `staging-admin.example.com` unless you guessed the name. CT
logs are a public record of every certificate issued, which means every host anyone ever put a
certificate on, including the internal one someone published by accident in 2023. Understand why
that makes it the single highest-value free source in attack surface management, and why the results
include hosts that no longer exist.

**Then the concurrency question.** Four hundred hostnames to resolve. Sequentially, that's minutes.
All at once, you have four hundred concurrent DNS queries from one process and a resolver that stops
answering. What's the shape that sits between those, and how do you stop it from starving every
other job on the worker's event loop?

## Search for

- dnspython asyncio resolver resolve_name
- crt.sh json api query domain
- certificate transparency wildcard san parsing
- asyncio semaphore limit concurrency
- respx mock httpx responses fixture
- graceful degradation partial results api design
