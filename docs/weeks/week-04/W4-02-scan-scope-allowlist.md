# W4-02 · Scan scope: a default-deny allowlist

**Owner:** Islam · **Reviewer:** Zyad + mentor · **Effort:** 4h · **Depends on:** W4-01

> ⚠️ **Scope.** Until W4-02 merges, `localhost` and the four `just lab-up` containers are the
> only things you may point any of this at. After it merges, the allowlist is. Anything else —
> a domain you own, your VPS, "just to test it" — **ask first, every time.**

🔑 Built *before* the scanner it guards, on purpose. A guardrail added afterwards is a guardrail
somebody can forget to call.

## What

This is the first week the code can hurt someone. A connect scanner pointed at the wrong address is
not a bug you get to explain afterwards — so before W4-04 exists, build the thing that decides where
it is allowed to point.

**Default deny.** An empty allowlist means nothing is scannable. Not "everything", not "localhost
only by accident" — nothing. There must be a test that empties the allowlist and asserts the scan is
refused, and it must fail if someone inverts the condition.

Build:

- **A scope configuration** — hostnames, IPs and CIDR ranges that may be scanned. For now this is
  configuration, not per-tenant data in the database. What goes in it is the four lab services as
  the **worker** sees them: `lab-nginx`, `lab-apache`, `lab-nonstandard`, `lab-tls-san` on the
  compose network, which resolve to container addresses — not the `localhost:8081` ports you use
  from your laptop. Per-tenant scope is a week-6 problem and you should say so in the PR rather than
  build it
- **A check that resolves first, then decides.** `lab-nginx` is a name. The allowlist is ultimately
  about addresses. Resolve the name, check the *address*, and hand the caller the resolved address
  to connect to — do not resolve, check, and let the scanner resolve again
- **Blocked by default, regardless of the allowlist:** link-local (`169.254.0.0/16`, and
  `169.254.169.254` in particular), IPv6 link-local, multicast, and anything in RFC1918 that is not
  explicitly listed. Loopback is a special case here because the lab *is* on loopback — which means
  you allow specific loopback ports, not loopback
- **A refusal that is loud and structured.** A blocked scan is a `403` at the API and a logged event
  in the worker with the target, the resolved address and the reason. Not a silent skip, not an
  empty result

**Make it unskippable.** The scanner should not be able to open a socket without having passed
through this. "Call `check_scope()` first" is a convention; a function that returns the connection —
or raises — is a mechanism. W2-07 made this exact argument about `TenantScopedRepository` and
tenant IDs. Make the same argument in code here, and say in the PR which of the two you built.

Tests:

- Empty allowlist refuses everything, including the lab
- A hostname resolving to an allowlisted address is permitted
- A hostname resolving to `169.254.169.254` is refused even if the *hostname* is allowlisted
- A CIDR entry permits an address inside it and refuses one outside
- The refusal path never opens a socket — assert on the mock, not on the result

## Expected outcome

`POST /targets/{id}/scans` for an out-of-scope target returns `403` with a reason, and the worker log
shows the refusal and no outbound connection attempt. Deleting the allowlist entry for the lab makes
every scanning test in the repository fail.

## Think about

**A scanner that takes a hostname and connects to it is an SSRF primitive.** That is not an insult —
it is the literal description of what you are building, and it is why the OWASP SSRF cheat sheet is
on this week's reading list rather than a security-week nicety.

Read it and then think about **DNS rebinding**: a hostname you resolved and approved can resolve to
something different half a second later when the scanner resolves it again. There is a reason this
task says "hand the caller the resolved address." Be able to explain it.

Also think about where the check belongs. At the API, so a bad target is rejected on creation? In
the job, so it is checked at scan time? In the socket layer, so nothing can bypass it? These are not
mutually exclusive and they catch different mistakes. Defending your answer is most of this review.

**This PR carries `needs-mentor-review`.** It is the one PR of the week that gets read line by line.

## Search for

- ssrf prevention allowlist resolved ip
- dns rebinding attack ttl
- python ipaddress ip_network is_private is_link_local
- cloud instance metadata service 169.254.169.254 block
- fail closed default deny authorization
- asyncio open_connection connect to resolved address
