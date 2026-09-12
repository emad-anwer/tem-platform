# Job Lifecycle

Postgres is the source of truth for scan history. Redis and arq are delivery and retry mechanisms; their job records are advisory and may expire.

A scan run is created once in `queued`, then moves through `running` to either `succeeded` or `failed`. Retries reuse the same run and increment `attempt`. A terminal row is idempotent: a redelivered job cannot resurrect it or create another run.

Retryable upstream failures use arq `Retry` with three maximum attempts and full-jitter exponential backoff. Invalid input and other terminal failures write `failed` immediately. Failure rows store only a short safe reason and the attempt number; exception payloads, credentials, connection strings, SQL, and tracebacks are not persisted or logged by the lifecycle code.

Each job has its arq deadline, and outbound HTTP callers should use `core.jobs.timeouts.outbound_http_timeout()` for connect, read, and total limits. A running row older than twice the job deadline is marked `failed` with `error_kind=stale` by `mark_stale_runs`; a later sweep can call that function periodically.
