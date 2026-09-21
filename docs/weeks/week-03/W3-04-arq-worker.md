# W3-04 · arq worker service and Compose wiring

**GitHub issue:** [#69](https://github.com/emad-anwer/tem-platform/issues/69)

**Owner:** Zyad · **Reviewer:** Arwa · **Effort:** 4h · **Depends on:** #66

The second process. Until now the platform has been one container that answers HTTP; from this task
on there is something else running, sharing the codebase and the database but not the request path.

## What

- Add **arq** to `pyproject.toml`, with the justification in the PR description referencing
  `DECISIONS.md` §4 — it is already the approved choice, so the PR explains *why it was*, briefly,
  rather than re-litigating it
- A `WorkerSettings` with the Redis connection, the function registry, startup and shutdown hooks,
  and sensible concurrency. Reuse the existing `core/redis.py` connection handling rather than
  opening a second, differently-configured client
- A `worker` service in `compose.yaml` sharing the app image, with its own command. Same env, same
  network, no exposed ports — it serves nothing
- `just worker` and `just worker-logs` recipes, alongside the existing ones
- **Graceful shutdown**: SIGTERM stops the worker taking new jobs and lets the in-flight one finish.
  A redeploy must not kill a scan halfway through and leave a row lying about
- Structured logging via the existing `structlog` setup, with the job ID and tenant ID on every line
  a job emits. Somebody will be reading these on Thursday to work out why one scan out of forty is
  stuck, with every other job's lines interleaved into the same stream

`redis_required` currently defaults to `False` — "in dev, Redis failure is tolerated". That is true
for the API. Decide whether it is true for a worker whose entire job is reading a queue, and make
the code say what you decided.

## Expected outcome

`just up` brings a worker up alongside the API. `just worker-logs` shows it picking up jobs.
`docker compose stop worker` finishes the current job and exits cleanly rather than being killed.

Stopping the worker leaves the API healthy and jobs queued — the two processes fail independently.

## Think about

**Worker concurrency is one event loop.** arq runs N jobs concurrently in a single process, which
means one synchronous blocking call — a DNS resolver that isn't async, a `requests` call, a
`time.sleep` — stalls every other job on that loop. Not slows: stalls. W3-07 has to resolve DNS for
hundreds of hostnames, so the person writing it needs to know this. Tell them, and put it in the PR
where they will read it.

Second: what does the worker do when Redis isn't there at startup? Crash-loop, or start and retry?
Both are defensible; a worker that starts, silently fails to connect, and reports itself healthy is
not.

## Search for

- arq WorkerSettings redis_settings functions
- docker compose multiple services same image different command
- sigterm graceful shutdown asyncio python
- docker compose stop_grace_period
- structlog contextvars bind job id
- asyncio blocking call event loop starvation
