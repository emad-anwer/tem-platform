# W4-05 · Redis-backed per-host rate limiting

**Owner:** Zyad · **Reviewer:** Islam · **Effort:** 4h · **Depends on:** W4-02

> ⚠️ **Scope.** Until W4-02 merges, `localhost` and the four `just lab-up` containers are the
> only things you may point any of this at. After it merges, the allowlist is. Anything else —
> a domain you own, your VPS, "just to test it" — **ask first, every time.**

Deliberately **parallel to W4-04, not behind it.** Build this against a fake caller so neither you
nor Arwa is blocked on the other.

## What

A scanner that is polite to a host is one that shares a budget with every other thing scanning that
host. The limit belongs to the **target**, not to the process — which is why it lives in Redis and
not in a `dict`.

Build:

- **A per-host limiter in Redis**, so two workers scanning `lab-nginx` share one budget rather than
  getting one each. This is the whole reason for the task; a limiter that works only inside one
  process is a `dict` with extra steps
- **One algorithm, chosen and justified.** Token bucket permits controlled bursts. Sliding window
  smooths them. The naive fixed window allows a 2× burst across the boundary and is the one people
  ship by accident. Pick one, say why in the PR, and know the failure mode of the one you picked
- **Atomically.** `GET` then `SET` from two workers is a race, and the race is exactly the case the
  limiter exists for. Redis gives you `INCR`, `EXPIRE`, pipelines and Lua — use whichever, but be
  able to say why it cannot double-count
- **A caller that waits rather than fails.** A scanner that gets rate-limited should slow down, not
  error. That means the limiter returns "wait 0.4s" and the caller sleeps — with a cap, so a
  misconfigured limit does not hang a job past its deadline
- **Configurable per host, with a default.** crt.sh, DNS and a customer's web server do not deserve
  the same politeness budget

Tests:

- N concurrent callers against one host never exceed the limit — measure it, don't assume it
- Two separate hosts do not share a budget
- Two limiter instances (simulating two workers) against one host share one budget. This is the
  test that proves the task
- A caller waits and proceeds rather than raising
- The wait is capped, and the cap is tested

Redis is already in the stack and already has a shared client — do not add a library for this.

## Expected outcome

Twenty concurrent requests at a limit of five per second take roughly four seconds and never exceed
five in any one-second window, whether they come from one process or two.

## Think about

The limiter has to be **in the path**, not beside it. A `RateLimiter` that a scanner is supposed to
`await` before each connection is a convention; something the scanner cannot get a connection
without going through is a mechanism. Same argument as W4-02, same argument W2-07 made about tenant
scoping — this is the third time the week has made it, which should tell you something.

Think about what happens to the arq job deadline. `job_timeout` is 300 seconds. A scan of 100 ports
at 5/second is 20 seconds; at 0.5/second it is 200; at 0.1/second it does not finish. The limiter
and the timeout are the same conversation, and the answer is probably that a slow scan should finish
in several runs rather than one very patient one — but that is a decision, so make it and write it
down.

Spend 45 minutes with Arwa on Monday before either of you writes code. Her semaphore bounds how many
connections *her scanner* has open. Your limiter bounds how fast *anything* touches one host. Two
limiters that don't know about each other is how a scanner stays comfortably under its semaphore and
still takes a host down.

## Search for

- token bucket vs sliding window rate limiting
- redis rate limiter INCR EXPIRE atomic
- redis lua script rate limit atomicity
- distributed rate limiting shared state
- fixed window boundary burst problem
- backoff sleep cap job deadline
