# W4-04 · Async TCP connect scanner

**Owner:** Tasneem · **Reviewer:** Arwa · **Effort:** 5h · **Depends on:** W4-02, W4-03

> ⚠️ **Scope.** Until W4-02 merges, `localhost` and the four `just lab-up` containers are the
> only things you may point any of this at. After it merges, the allowlist is. Anything else —
> a domain you own, your VPS, "just to test it" — **ask first, every time.**

🔑 The chokepoint of the week. W4-06, W4-07 and W4-10 are all behind it. **It must land Tuesday**,
and Tuesday's stand-up is an explicit go/no-go on it.

## What

The first code in this platform that connects to something.

Build a port scanner on `asyncio.open_connection` — standard library, no `scapy`, no raw sockets, no
root. It is a **TCP connect scan**: full three-way handshake, one per port. Slower and louder than a
SYN scan, and the only option available to an unprivileged container. Know that trade-off before you
start; you will be asked about it.

The scan:

- Takes a host that has **already passed W4-02's scope check**, and connects to the address that
  check returned — not to a name you resolve yourself
- Scans a **curated port list** (~100 interesting ports), not 1–65535. A short list finds more per
  second with less blast radius. Put the list in one place with a comment saying why those ports
- **Bounds its own concurrency with a semaphore.** This is the core of the task. A thousand
  coroutines with fifty inside the semaphore is the goal; a thousand open sockets is the bug. Know
  what your number is and why
- Puts a **timeout on every connection attempt**, via `asyncio.wait_for` or `asyncio.timeout`.
  Without one, a filtered port holds a coroutine until the OS gives up — which is minutes
- Distinguishes **three** outcomes, not two: `ConnectionRefusedError` is closed, a successful
  handshake is open, a timeout is filtered. The third is the interesting one
- **Closes every connection it opens**, including on the error paths. A leaked writer is a file
  descriptor you get back when the process exits
- Writes `open_port` findings through W4-03's generic path, with the port and protocol in the
  fingerprint as ADR-0004 decided

**One addressing detail that will cost somebody an hour.** `docs/target-lab.md` documents the lab by
its *published* ports — `localhost:8081`, `8082`, `8888`, `8443`. Those are the ports your laptop
sees. The worker is a container on the compose network and reaches the same services as `lab-nginx`,
`lab-apache`, `lab-nonstandard`, `lab-tls-san` on their **container** ports — `80`, `80`, `8888`,
`443`. Both views are correct and the scanner only ever sees the second. Write down which one your
tests assert on.

Tests, against the lab (`just lab-up`):

- `lab-nginx` shows its HTTP port open; a port you know is closed shows closed
- `lab-nonstandard` on 8888 is found — the point of that container
- Concurrency never exceeds the semaphore limit — instrument it and assert, don't eyeball it
- A host that refuses everything completes in roughly the timeout, not N × timeout
- Every connection is closed after the scan: assert on the count, not on a feeling

## Expected outcome

`just lab-up`, one scan, and all four lab services come back as `open_port` findings — in seconds,
with a number you can point at that says how many sockets were open at once.

## Think about

**If it is much faster than you expected, something is wrong.** That is not a joke and it is the
most common outcome of this task. It usually means the semaphore is around the wrong thing —
`async with sem: tasks.append(asyncio.create_task(...))` bounds *task creation*, which is free, and
bounds nothing at all. The semaphore goes inside the coroutine that does the work.

Think about what happens on your own laptop at a high limit: the process file-descriptor limit, the
target's connection backlog, and your OS's ephemeral port range. Pick a number you can justify
rather than the one that made the test pass.

`lab-nonstandard` exists in the lab specifically because a scanner that only checks 80 and 443
misses it. If your port list is short enough to be fast and long enough to find 8888, you have
understood the trade-off the task is about.

One thing this task does **not** do: touch the rate limiter. W4-05 is being built in parallel by
Zyad against a fake caller. You bound *your own* concurrency; he bounds *everyone's* access to one
host. Spend 45 minutes with him on Monday before either of you writes it — two limiters that don't
know about each other is how a scanner stays under its semaphore and still hammers one host at
fifty requests a second.

## Search for

- asyncio open_connection timeout wait_for
- asyncio semaphore limit concurrent connections pattern
- tcp connect scan vs syn scan unprivileged
- connectionrefusederror vs timeout port filtered
- ulimit file descriptors ephemeral port exhaustion
- asyncio writer close wait_closed cleanup
