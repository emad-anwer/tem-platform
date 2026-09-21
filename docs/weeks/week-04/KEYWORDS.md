Everything here connects to something you are actually building this week. Nothing is background
reading for its own sake.

**This week's shape:** the platform sends its own packets for the first time. Week 3 discovered
subdomains by asking other people's servers politely; this week the code opens TCP connections,
reads what is listening, and parses certificates. Three things follow from that, and all three are
tasks: concurrency has to be *bounded*, scope has to be *enforced in code*, and one finding kind has
to become four without four fingerprints.

> ### ⚠️ Before you write any scanning code
>
> Until **W4-02 is merged**, the only things you may point a scanner at are `localhost` and the four
> lab containers (`just lab-up`). Not a domain you own. Not your VPS. Not "just to test it."
>
> A port scan against infrastructure that isn't ours is — depending on where it lands — a
> terms-of-service violation, an abuse report, or a criminal matter. The lab exists precisely so
> nobody has to make a judgement call. **If you think you need to scan something else, ask first.**

## Concepts you're expected to understand by Thursday

You will be asked about these in the Thursday demo — not to recite a definition, but to defend a
choice you made.

| Concept | What you should be able to say |
|---|---|
| **TCP connect scan** | A full three-way handshake per port. No root, no raw sockets, slower than SYN scanning, and logged by everything it touches |
| **Bounded concurrency** | A semaphore limits how many coroutines are *doing the work* at once. 1,000 tasks with 50 running is the goal; 1,000 open connections is the bug |
| **Backpressure** | What a producer does when the consumer is behind: block, drop, or grow forever. Only the third requires no decision, which is why it's the accidental default |
| **Connect timeout** | The deadline on the handshake itself. Without it, a filtered port holds a coroutine until the OS gives up — minutes, not seconds |
| **Open / closed / filtered** | Handshake succeeded, actively refused, or silence. Three outcomes, not two, and the third is where the interesting hosts are |
| **Banner grabbing** | What a service volunteers about itself in its first bytes. Evidence of what's running, not proof — banners are trivially edited |
| **Technology fingerprinting** | Deriving a stack from headers, cookies, body markers and paths. A rules table with confidences, because every individual signal can be faked |
| **Token bucket / sliding window** | Two rate-limiting algorithms with two failure modes. The naive fixed window permits a 2× burst across the boundary, and it's the one people ship |
| **Default-deny allowlist** | Nothing is scannable until it's listed. A denylist is the same idea with the failure mode inverted — and the failure mode is the entire point |
| **SSRF / link-local metadata** | `169.254.169.254` hands cloud credentials to anything that asks. A scanner that accepts a hostname is an SSRF primitive until it refuses that address |
| **X.509 SAN** | Every name a certificate is valid for, listed inside the certificate. Free attack-surface discovery from a host you already found |
| **Change detection** | The set difference between two runs — `new`, `reappeared`, `resolved`, `unchanged`. The product is the diff, not the inventory |

## Search terms

Each task issue has its own **Search for** list at the bottom. Start there — they're scoped to what
that specific task needs.

## Resources

Eight things. Most are short; the two longest are the two that matter most. This is not a course.

**[Python docs — asyncio streams: `open_connection`](https://docs.python.org/3/library/asyncio-stream.html)** *(official, short)*
The entire TCP scanner is this one function plus a timeout. Read what it raises —
`ConnectionRefusedError` means closed, `TimeoutError` means filtered, and that distinction *is* the
scan result.

**[Python docs — asyncio synchronization primitives](https://docs.python.org/3/library/asyncio-sync.html)** *(official, short)*
`Semaphore` specifically. It bounds how many coroutines are *inside* the block, not how many exist —
which is the misunderstanding behind most "my semaphore didn't work" bugs.

**[Nmap Book — TCP connect scan](https://nmap.org/book/scan-methods-connect-scan.html)** *(short)*
Why connect scanning is the slow, loud, unprivileged option, and what SYN scanning buys that we
can't have from a container. The reasoning behind W4-04, not the code.

**[Nmap Book — Legal issues](https://nmap.org/book/legal-issues.html)** *(first two sections)*
Port scanning is not universally legal, universally illegal, or universally harmless. Read this
before W4-02, and understand that the allowlist is what stands between a typo and somebody's abuse
desk.

**[OWASP — SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)**
A scanner that takes a hostname and connects to it *is* an SSRF primitive, by design. The canonical
list of what to block, and why `169.254.169.254` is on it. Directly W4-02.

**[Cloudflare — How we built rate limiting capable of scaling to millions of domains](https://blog.cloudflare.com/counting-things-a-lot-of-different-things/)**
The sliding-window counter, why the naive fixed window allows a 2× burst, and why an approximation
is the right answer. W4-05 in one article.

**[`cryptography` — X.509 reference](https://cryptography.io/en/latest/x509/reference/)** *(official — skim, then use as reference)*
Loading a certificate and reading its extensions. You want `SubjectAlternativeName`,
`not_valid_after_utc` and the fingerprint. Ignore the rest until you need it.

**[arq — cron jobs](https://arq-docs.helpmanual.io/#cron-jobs)** *(official, one page)*
The whole scheduling API. Read `run_at_startup` and think about what it means for a worker that
restarts on every deploy. Directly W4-09.

## How to use these

Read the resource when the task needs it, not before.

**Timebox being stuck to 45 minutes**, then ask in the team channel. A good question shows your
work: what you tried, what you expected, what happened instead.

Two exceptions this week, both because the code now sends packets:

- **Before pointing a scanner at anything that isn't `localhost` or a lab container, ask.** Not "ask
  if unsure" — ask, every time, until W4-02 is merged and the allowlist is what decides.
- **If a scan finishes much faster than you expected, that's a bug report, not good news.** It
  almost always means the semaphore or the rate limiter isn't actually in the path.
