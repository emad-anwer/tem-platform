# Week 4 — The platform sends its own packets

**Sunday–Thursday · Lead: Arwa**

Code repository: **<https://github.com/emad-anwer/tem-platform/>** — every active task below is a
live issue there.
Milestone: [Week 4 — ASM Depth: the scanner they wrote themselves](https://github.com/emad-anwer/tem-platform/milestone/4) ·
Keywords issue: [#109](https://github.com/emad-anwer/tem-platform/issues/109)

> ### ⚠️ Read this before you write any scanning code
>
> Until **W4-02 is merged**, the only things you may point a scanner at are `localhost` and the four
> lab containers (`just lab-up`). Not a domain you own. Not your VPS. Not "just to test it."
>
> This is not a formality and it is not about trust. A port scan against infrastructure that isn't
> ours is, depending on where it lands, a terms-of-service violation, an abuse report, or a criminal
> matter. The lab exists precisely so that nobody has to make a judgement call about this.
>
> **If you think you need to scan something else: ask first.** Every time.

Week 3 built a pipeline that carries one kind of finding, discovered by asking other people's
servers politely. This week the code starts **connecting to things**, and almost everything hard
about week 4 follows from that.

Three consequences, and all three are tasks:

1. `asyncio.gather` over a thousand ports is four lines and a denial-of-service. Bounding it is the
   first real skill of the week.
2. "Where are we allowed to scan?" stops being a sentence in a document and becomes a code path —
   one that has to be impossible to skip.
3. One finding kind becomes four. Week 3's fingerprint has `"subdomain|"` hardcoded inside it, in
   `core`. That has to stop being true before four people invent four fingerprints.

**And one question nobody has had to answer yet.** Open `src/app/modules/asm/` and look at it:
`models.py`, `repository.py`, `service.py`, `route.py`, `schemas.py`, `api.py` — six empty files.
`brand/`, `darkweb/` and `intel/` are the same. They were scaffolded in week 1 and nothing has ever
been written into them. Every line this platform has lives in `core`, including
`core/discovery.py`, which is ASM work by any reading of it.

That was fine while there was one module. This week produces code that belongs to ASM and to
nothing else, so **W4-01 has to decide where it goes** — and decide it as a rule, not case by case.
If the rule turns out to be "almost everything stays in `core`", that is a defensible answer, but
then somebody should ask what the four empty packages are for. A boundary that enforces nothing is
worse than no boundary, because everyone assumes it is doing something.

## Tasks

| # | Task | Owner | Reviewer | Effort | Depends on | Issue |
|---|---|---|---|---|---|---|
| [W4-01](W4-01-finding-taxonomy-adr.md) 🔑 | ADR-0004: finding kinds, fingerprints, change semantics | Tasneem | all four + mentor | 2h + 45m | — | [#93](https://github.com/emad-anwer/tem-platform/issues/93) |
| [W4-02](W4-02-scan-scope-allowlist.md) 🔑 | Scan scope: a default-deny allowlist | Islam | Zyad + mentor | 4h | W4-01 | [#94](https://github.com/emad-anwer/tem-platform/issues/94) |
| [W4-03](W4-03-finding-kinds.md) 🔑 | Finding kinds and a fingerprint that isn't about subdomains | Zyad | Arwa + mentor | 4h | W4-01 | [#95](https://github.com/emad-anwer/tem-platform/issues/95) |
| [W4-04](W4-04-tcp-connect-scanner.md) 🔑 | Async TCP connect scanner | Tasneem | Arwa | 5h | W4-02, W4-03 | [#96](https://github.com/emad-anwer/tem-platform/issues/96) |
| [W4-05](W4-05-rate-limiting.md) | Redis-backed per-host rate limiting | Zyad | Islam | 4h | W4-02 | [#97](https://github.com/emad-anwer/tem-platform/issues/97) |
| [W4-06](W4-06-http-prober.md) | HTTP prober: status, title, headers, tech fingerprint | Islam | Zyad | 5h | W4-04, W4-05 | [#98](https://github.com/emad-anwer/tem-platform/issues/98) |
| [W4-07](W4-07-tls-certificates.md) | TLS certificate parsing, and SANs back into discovery | Arwa | Tasneem | 4h | W4-04 | [#99](https://github.com/emad-anwer/tem-platform/issues/99) |
| [W4-08](W4-08-change-detection.md) | Change detection between runs | Zyad | Islam | 4h | W4-03 | [#100](https://github.com/emad-anwer/tem-platform/issues/100) |
| [W4-09](W4-09-scheduled-scans.md) | Scheduled scans and the stale-run sweeper | Islam | Zyad | 3h | W4-03 | [#101](https://github.com/emad-anwer/tem-platform/issues/101) |
| [W4-10](W4-10-scan-orchestration.md) | Scan orchestration: one run, three sources | Arwa | Islam | 3h | W4-04, W4-06, W4-07 | [#102](https://github.com/emad-anwer/tem-platform/issues/102) |
| [W4-11](W4-11-asm-docs.md) | ASM scanner docs and the scope policy page | Tasneem | Arwa | 2h | W4-10 | [#103](https://github.com/emad-anwer/tem-platform/issues/103) |

**Optional — do not start unless Wednesday is clean:**

| # | Task | Owner | Reviewer | Effort | Depends on |
|---|---|---|---|---|---|
| [W4-12](W4-12-machine-access.md) | Machine access: Zitadel service users | — | Tasneem | 4h | — |

**W4-12 is deliberately not filed as an issue.** An unassigned issue in an active milestone reads
as "someone forgot" rather than "we decided". It stays here, ready, if Wednesday comes in clean.

## Bugs and debt from week 3

Five things the week-3 review found. Four of them are already inside a week-4 task — they are listed
separately so they close with a reason attached rather than going quiet, and so you can see what
your own code looked like to someone reading it cold a week later.

| # | What | Closed by | Owner | Effort | Issue |
|---|---|---|---|---|---|
| [BUG-01](BUG-01-hardcoded-subdomain-kind.md) | `core` hardcodes `"subdomain"` in three places | W4-03 | Zyad | in W4-03 | [#104](https://github.com/emad-anwer/tem-platform/issues/104) |
| [BUG-02](BUG-02-mark-stale-runs-has-no-caller.md) | `mark_stale_runs` has no caller — dead since it merged | W4-09 | Islam | in W4-09 | [#105](https://github.com/emad-anwer/tem-platform/issues/105) |
| [BUG-03](BUG-03-run-scheduled-scan-is-a-stub.md) | `run_scheduled_scan` is a registered stub that logs success | W4-10 | Arwa | in W4-10 | [#106](https://github.com/emad-anwer/tem-platform/issues/106) |
| [BUG-04](BUG-04-dead-worker-context-module.md) | `worker/context.py` — a second, dead way to bind job context | W4-10 | Arwa | in W4-10 | [#107](https://github.com/emad-anwer/tem-platform/issues/107) |
| [BUG-05](BUG-05-pipeline-reads-have-no-permission.md) | Four pipeline GET routes have no permission check | itself | **Arwa** | **1h** | [#108](https://github.com/emad-anwer/tem-platform/issues/108) |

**Only BUG-05 is extra work.** The other four are already paid for inside a task you were going to
do anyway. BUG-05 is Thursday work, or whenever a gap opens — never ahead of W4-10.

None of the five is a reprimand. Week 3 was asked for one finding kind and shipped one finding kind;
generalising on the second case is correct, not late. What is worth sitting with is BUG-02: a
function that is *tested* and never *reached* is a shape you will meet for the rest of your career,
and the test suite will be green every time.

## Load

| Intern | Tasks | Task hours | + review/standups | Total |
|---|---|---|---|---|
| **Arwa** (lead) | 07, 10, BUG-05 | 8h | +4h lead, +3h review | **15h** |
| **Islam** | 02, 06, 09 | 12h | +3h | **15h** |
| **Zyad** | 03, 05, 08 | 12h | +3h | **15h** |
| **Tasneem** | 01, 04, 11 | 9h | +3h | **12h** |

41h of task work against 20h/week each — the same shape as week 3, which held.

**Tasneem is lightest on purpose.** W4-04 is the task three other tasks are waiting on. If it slips
she needs room to recover it without W4-06, W4-07 and W4-10 stalling behind her — and the lead, who
has stand-ups and integration to run, is the wrong person to put underneath that.

## Critical path

```
Sunday     W4-01  ADR-0004: kinds, fingerprints, change semantics
              │
Monday        ├─→ W4-02  scope guard
              │      └─→ W4-05  rate limiter        ── parallel to W4-04, not behind it
              └─→ W4-03  finding kinds
                     ├─→ W4-08  change detection    ── independent branch
                     └─→ W4-09  scheduled scans     ── independent branch

Tuesday    W4-04  port scanner        ← W4-02 + W4-03        ★ chokepoint

Wednesday  W4-06  HTTP prober         ← W4-04 + W4-05
           W4-07  TLS certificates    ← W4-04

Thursday   W4-10  orchestration       ← W4-04 + W4-06 + W4-07
           W4-11  docs                ← W4-10

           BUG-05 read permissions    ── no dependencies, fits any gap

           W4-12  machine access      ── optional, nothing depends on it
```

**W4-01 must merge Sunday.** W4-02 and W4-03 both stall Monday morning otherwise, and everything
else is behind those two.

**W4-04 must land Tuesday.** It is the chokepoint of the week: W4-06, W4-07 and W4-10 are all behind
it. Tuesday's stand-up is an explicit go/no-go on it, not a status round.

**W4-05 is deliberately parallel to W4-04**, not behind it. Build the limiter against a fake caller,
not against the scanner — otherwise two people are blocked on one person's socket code.

## Not this week

Deliberately deferred, so nobody builds them early:

- **`nmap`, `masscan`, `subfinder`, `nuclei`** — the whole point is that you write the scanner.
  Wrapping an external tool comes later, when you know what it is doing for you
- **SYN scanning, UDP scanning, raw sockets** — need root and a privileged container. Connect
  scanning from an unprivileged process is the constraint; work inside it
- **Full 65,535-port sweeps** — a curated list of ~100 interesting ports finds more, faster, with
  less blast radius. Scanning everything is a decision you make once you can measure the cost
- **Deep service version detection** — `nginx/1.25.4` from a banner is enough. Probe-and-match
  version fingerprinting is a project, not a task
- **Alerts and notifications** — week 6. W4-08 produces the change *data*; nothing emails anyone yet
- **ClickHouse** — week 5. Findings stay in Postgres
- **Distributed / multi-worker scanning** — one worker is enough. W4-05 is built as if there were
  several, which is the part that matters
- **Scanning anything outside the lab** — see the banner at the top

---

## Concepts you're expected to understand by Thursday

You'll be asked about these at the demo — not to recite a definition, but to defend a choice.

| Concept | What you should be able to say |
|---|---|
| **TCP connect scan** | A full three-way handshake per port. No root, no raw sockets, slower than SYN scanning, and logged by everything it touches |
| **Bounded concurrency** | A semaphore limits how many coroutines are *doing the work* at once. 1,000 tasks with 50 running is the goal; 1,000 open connections is the bug |
| **Backpressure** | What a producer does when the consumer is behind: block, drop, or grow forever. Only the third requires no decision, which is why it's the default |
| **Connect timeout** | The deadline on the handshake. Without it, a filtered port holds a coroutine until the OS gives up — minutes, not seconds |
| **Open / closed / filtered** | Handshake succeeded, actively refused, or silence. Three outcomes, not two, and the third one is where the interesting hosts are |
| **Banner grabbing** | What a service volunteers about itself in its first bytes. Evidence of what's running, not proof — banners are trivially edited |
| **Technology fingerprinting** | Deriving a stack from headers, cookies, body markers and paths. A rules table with confidences, because every single signal can be faked |
| **Token bucket / sliding window** | Two rate-limiting algorithms with two failure modes. The naive fixed window permits a 2× burst across the boundary, and that's the one people ship |
| **Default-deny allowlist** | Nothing is scannable until it's listed. A denylist is the same idea with the failure mode inverted — and the failure mode is the entire point |
| **SSRF / link-local metadata** | `169.254.169.254` hands cloud credentials to anything that asks. A scanner that accepts a hostname is an SSRF primitive until it refuses that address |
| **X.509 SAN** | Every name a certificate is valid for, listed inside the certificate. Free attack-surface discovery from a host you already found |
| **Change detection** | The set difference between two runs — `new`, `reappeared`, `resolved`, `unchanged`. The product is the diff, not the inventory |

## Search terms

Each task file has its own **Search for** list at the bottom, scoped to that task. Start there.

## Resources

Eight things. Most are short; the two longest are the two that matter most.

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
before W4-02 and understand that the allowlist is what stands between a typo and somebody's abuse
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
