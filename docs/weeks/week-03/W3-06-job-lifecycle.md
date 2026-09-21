# W3-06 · Job lifecycle: states, retries, timeouts, failure

**GitHub issue:** [#71](https://github.com/emad-anwer/tem-platform/issues/71)

**Owner:** Arwa · **Reviewer:** Zyad · **Effort:** 4h · **Depends on:** #67, #68

The happy path is twenty minutes of this task. The rest is what happens when it doesn't work.

## What

Make `ScanRun` an honest record of what actually happened.

- Implement the state machine ADR-0003 specified — `queued → running → succeeded | failed`, or
  whatever it decided — with the transitions enforced in one place rather than assigned ad hoc
  across the codebase
- **Retries.** `max_tries` and backoff on the arq side; on your side, a retry must *not* create a
  second `ScanRun`. The run is the unit of work; the attempt is not
- **Backoff with jitter.** Four workers retrying a failed crt.sh call in lockstep is a self-inflicted
  outage. Randomise
- **Two timeouts.** The job's own deadline (`job_timeout`), and the HTTP timeout on every outbound
  call the job makes. Without the second, a hung socket holds a worker slot until the first fires —
  and if you forgot to set the first, forever
- **Distinguish retryable from terminal.** A 502 from crt.sh is worth retrying. An invalid domain is
  not, and retrying it three times just delays telling the user something they need to know
- **The stuck run.** A worker killed mid-job leaves a row in `running` with nobody working on it.
  Decide what happens: a heartbeat, a stale-run sweep, a `started_at` age check on read, or an
  explicit "we accept this and here's how an operator spots it". Any of those is a real answer.
  Not having thought about it is not
- Failure detail on the row: what failed, when, on which attempt. Enough that someone reading it
  Thursday morning knows whether to retry or fix something
- **Never log a secret, token or connection string** in a failure path. Exception messages contain
  more than you expect

Tests via W3-03's harness: a retried job updates one run rather than creating two; a job that
exceeds its deadline lands in `failed` with a reason; a terminal error doesn't retry.

## Expected outcome

Killing the worker mid-scan leaves a `ScanRun` a human can explain. Every failure mode you can name
produces a row that says which one it was.

## Think about

**Who owns the state — arq or your table?** arq tracks job results in Redis, with a TTL. Your
`ScanRun` row is in Postgres, permanently. These two will disagree eventually: Redis loses the job
record, or your row says `running` while arq says the job finished, or arq retries a job whose row
already says `failed`. Decide now which one is the source of truth for "what happened to this scan",
and make the other one advisory.

**Then the harder question.** At-least-once delivery means a job may run twice even without a retry
— a network partition, a worker that dies after finishing the work but before acknowledging. So a
run in state `succeeded` can be handed to a worker again. What does your code do? "It can't happen"
is the answer that produces the week 5 bug nobody can reproduce.

## Search for

- arq retry max_tries Retry exception
- exponential backoff full jitter algorithm
- transient vs permanent failure classification
- httpx timeout connect read total
- stale job detection heartbeat visibility timeout
- state machine transition validation python
