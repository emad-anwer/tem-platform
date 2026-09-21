Everything here connects to something you are actually building this week. Nothing is background
reading for its own sake.

**This week's shape:** work leaves the request path. The API stops doing scans and starts scheduling
them; a separate worker process does the work; `Target`, `ScanRun` and `Finding` become the spine
that all four modules will eventually plug into. The queue will deliver some jobs twice — that is
normal, and your design has to survive it.

## Concepts you're expected to understand by Thursday

You will be asked about these in the Thursday demo — not to recite a definition, but to defend a
choice you made.

| Concept | What you should be able to say |
|---|---|
| **Task queue / worker** | The API enqueues and returns; a separate process does the work. The request path never waits for a scan to finish |
| **At-least-once delivery** | The queue guarantees the job runs, not that it runs once. Duplicate execution is normal operation, not an incident |
| **Idempotent job** | Running it twice leaves the same state as running it once — a property of the work you wrote, not a promise the queue made |
| **Fingerprint / finding identity** | The deterministic key deciding whether this is a new finding or the same one seen again. It is what makes change detection possible next week |
| **Job state machine** | `queued → running → succeeded \| failed`, with every transition written down — including the ones nobody enqueues, like a worker dying mid-run |
| **Retry and exponential backoff with jitter** | Retry only what is safe to retry, wait longer each time, and randomise the wait — or four workers retry in lockstep and take the source down |
| **Job timeout vs client timeout** | The deadline on the whole job, and the deadline on each HTTP call inside it. Missing the second makes the first your only defence against a hang |
| **Worker concurrency** | N jobs on one event loop in one process. One blocking call stalls every other job on that loop |
| **Tenant context without a request** | A job carries `tenant_id` in its payload and must establish the same scope middleware would. If it forgets, the repository must fail closed rather than return everything |
| **Graceful shutdown** | SIGTERM means stop accepting new jobs and finish the current one — not drop it half-written |
| **Transaction boundary** | Who decides what a unit of work is. One commit per scan or one commit per row is the same code and a very different program |
| **Graceful degradation of a source** | crt.sh being down returns fewer results, never an exception. No demo depends on a third party being up |

## Search terms

Each task issue has its own **Search for** list at the bottom. Start there — they're scoped to what
that specific task needs.

## Resources

Seven things. All short, all directly applicable. This is not a course.

**[arq — documentation](https://arq-docs.helpmanual.io/)** *(official, and short enough to read entirely)*
The whole library is small. Read the job lifecycle and `WorkerSettings` sections properly —
`max_tries`, `job_timeout` and `Retry` are most of W3-06 in three parameters.

**[AWS Builders' Library — Timeouts, retries, and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)**
Why "retry three times" is a denial-of-service against your own dependency, and why the fix is
randomness. Two pages, and it is the reasoning W3-06 needs rather than the code.

**[Brandur — Implementing Stripe-like idempotency keys](https://brandur.org/idempotency-keys)** *(skim — you read the Stripe doc in week 2)*
The follow-on to what you already know: what idempotency looks like when nobody supplies a key and
the operation has to be intrinsically repeatable. Directly W3-08.

**[Certificate Transparency — how it works](https://certificate.transparency.dev/howctworks/)** *(short)*
Why a public log of every issued certificate is a subdomain discovery tool, and why it finds hosts
that DNS enumeration never will. The domain lesson behind W3-07.

**[dnspython — asyncio resolver](https://dnspython.readthedocs.io/en/stable/async.html)** *(official)*
The API W3-07 needs, and the reason the blocking resolver would stall every other job sharing the
worker's event loop.

**[Martin Fowler — BlueGreenDeployment](https://martinfowler.com/bliki/BlueGreenDeployment.html)** *(optional track — park it with W3-10)*
Why migrations and deploys are ordered rather than simultaneous, and what "the old code must survive
the new schema" means in practice. Staging is deferred, so this keeps until the task does.

**[SQLAlchemy — Session basics: committing and the unit of work](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)** *(official)*
What a session actually does between `add()` and `commit()`, and why the repository committing on
every call is a design decision rather than a detail. Directly W3-13.

## How to use these

Read the resource when the task needs it, not before.

**Timebox being stuck to 45 minutes**, then ask in the team channel. A good question shows your
work: what you tried, what you expected, what happened instead.

One exception this week: **if a job hangs and you cannot tell whether it is running, queued or
dead, ask immediately.** Debugging a stuck worker by staring at it is the least productive hour
available to you, and knowing where to look is the point of W3-06 rather than a prerequisite for it.
