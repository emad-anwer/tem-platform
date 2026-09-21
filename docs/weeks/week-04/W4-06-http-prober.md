# W4-06 · HTTP prober: status, title, headers, technology fingerprint

**Owner:** Islam · **Reviewer:** Zyad · **Effort:** 5h · **Depends on:** W4-04, W4-05

> ⚠️ **Scope.** Until W4-02 merges, `localhost` and the four `just lab-up` containers are the
> only things you may point any of this at. After it merges, the allowlist is. Anything else —
> a domain you own, your VPS, "just to test it" — **ask first, every time.**

## What

An open port is a fact with very little meaning. This task turns `80/tcp is open` into
`nginx 1.25.4 serving "TEM Target Lab - Nginx Web Server"`.

For every `open_port` finding on a port that might speak HTTP, probe it and record:

- **Status code** and the final URL after redirects — and a cap on how many redirects you follow,
  because a redirect loop is a hang and a redirect off-host is a scope escape that has to go back
  through W4-02's check
- **The `<title>`**, if there is one. Parse it defensively: a title is untrusted input from a host
  you do not control, it can be 4MB long, and it can contain anything
- **Response headers worth keeping** — `Server`, `X-Powered-By`, `Content-Type`, and the set of
  cookie names. Not the cookie *values*: those are somebody's session tokens and they do not belong
  in your database or your logs
- **A technology fingerprint** — a rules table, not an if-chain. A rule is (signal, pattern,
  technology, confidence): `Server: nginx/([\d.]+)` → nginx, version captured, high confidence.
  `X-Powered-By: PHP/([\d.]+)` → PHP. A `wp-content` path in the body → WordPress, lower confidence.
  Evaluate them all, keep the matches with their confidences
- **A response body cap.** Read the first N kilobytes and stop. A host that streams forever is a
  memory exhaustion, and you are reading a `<title>` from the first 2KB anyway

Every request goes through **W4-05's limiter** and uses `outbound_http_timeout()` from
`core/jobs/timeouts.py` — the timeouts W3-06 already defined. Do not invent new ones.

Writes `http_service` findings through W4-03's path.

Tests, against the lab:

- `lab-nginx` → 200, `nginx/1.25.4`, `PHP/8.2.10` from `X-Powered-By`, the documented title
- `lab-apache` → `Apache/2.4.52`, and the fingerprint distinguishes it from nginx
- `lab-nonstandard` on 8888 → probed, because "HTTP lives on 80" is the assumption this container
  exists to break
- A port that is open and does **not** speak HTTP → no finding, no exception, no hang
- A redirect chain terminates at the cap
- An oversized body is truncated, not buffered
- A cookie value never appears in a finding or a log line

`docs/target-lab.md` has the exact expected values in its ground-truth table. Use them.

## Expected outcome

One scan of the lab produces four `http_service` findings with correct server versions, titles and
technology matches, matching the ground-truth table byte for byte where the table is specific.

## Think about

**Everything you parse here comes from a host you do not control.** A malicious target sets
`Server:` to 64KB of garbage, returns a 4MB `<title>`, redirects you to `169.254.169.254`, or
streams a body that never ends. Each of those is a real technique and each has a one-line defence.
Write the defences; then write the test that proves them by feeding the prober exactly that.

Think about what a fingerprint *claim* is worth. `Server: nginx` is what the host chose to tell you,
and hosts lie — sometimes to be secure, sometimes to be confusing. That is why rules carry a
confidence and why the finding records the *evidence* (the header that matched) alongside the
conclusion. An analyst who cannot see why you said "nginx" cannot disagree with you.

Cookie names are useful fingerprints (`PHPSESSID`, `JSESSIONID`, `wordpress_logged_in_*`). Cookie
values are credentials. The line between those two is one `.split("=")` and it is the kind of thing
that ends up in a log file and stays there. **No secrets, tokens or credentials in logs — ever.**

## Search for

- httpx follow_redirects max_redirects limit
- wappalyzer fingerprint rules json
- http response streaming read limit bytes
- html title parsing without full parser
- server header spoofing banner reliability
- httpx response.aiter_bytes truncate
