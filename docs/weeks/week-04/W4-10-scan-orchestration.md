# W4-10 · Scan orchestration: one scan run, three sources

**Owner:** Tasneem · **Reviewer:** Islam · **Effort:** 3h · **Depends on:** W4-04, W4-06, W4-07

> ⚠️ **Scope.** Until W4-02 merges, `localhost` and the four `just lab-up` containers are the
> only things you may point any of this at. After it merges, the allowlist is. Anything else —
> a domain you own, your VPS, "just to test it" — **ask first, every time.**

The integration task, and the lead's. Three people built three scanners this week; this is where
they become one scan.

## What

`POST /targets/{id}/scans` currently runs subdomain discovery and nothing else. After this task it
runs the whole ASM pipeline as **one `ScanRun`**:

```
scope check (W4-02)
  └─ subdomain discovery (W3-07)
       └─ port scan (W4-04)
            ├─ HTTP probe (W4-06)
            └─ TLS certificate (W4-07)
                 └─ SANs back into discovery
```

Build:

- **One run, several stages.** All findings from one API call belong to one `ScanRun`, and
  `last_seen_run_id` points at it. Four runs for one scan would break W4-08's diff on day one
- **Stage failures degrade, they don't abort.** crt.sh being down means fewer subdomains, not a
  failed scan — `DECISIONS.md` §5, and W3-07 already built the source interface that way. Extend the
  same discipline: a TLS parse failure on one host does not lose the port findings. `ScanRun` already
  has `sources_attempted` and `sources_degraded`; use them rather than adding fields
- **Every stage goes through the scope check.** A SAN discovered in W4-07 becomes a host that W4-04
  might scan next run. That path has to re-enter W4-02's check, not inherit an approval from the
  target that found it
- **Counts that mean something.** `findings_count` and `new_findings_count` across all stages, not
  per stage

Also in this task: **`src/app/core/jobs/scan.py::run_scheduled_scan` is a registered stub** with a
`# actual scan orchestration...` comment in the middle of it. It is in `JOB_REGISTRY` and does
nothing. Either it becomes the real orchestrator or it goes; do not leave a third thing.

Tests:

- One API call → one `ScanRun` → findings of four kinds, all with the same `last_seen_run_id`
- A stage that raises → the run still succeeds, degraded, with the failure recorded
- A stage that finds nothing → not an error
- `JOB_REGISTRY` has no stub in it
- End to end against the lab: `POST` a target, poll the run, `GET /findings`, and every value in
  `docs/target-lab.md`'s ground-truth table is there

## Expected outcome

The week's deliverable script runs top to bottom against the lab on a clean clone. That is the
Thursday demo, and you are the one driving it.

## Think about

You are the reviewer's customer this week: three people's code, none of it yours, arriving Tuesday
and Wednesday. The integration is your job, but so is the *information*. If W4-04 is not landing on
Tuesday, W4-06 and W4-07 need to hear that from you at Tuesday's stand-up, not discover it on
Thursday.

**Islam reviews this rather than Arwa**, deliberately. He owns the scope guard every source has to
pass through and he wrote the HTTP prober — so he is the person most likely to notice a stage that
quietly skipped the check. That is the specific thing to make easy for him to verify: make it
obvious, from reading the orchestrator, that there is no path to a socket that does not go through
W4-02.

Think about where the stages run. All in one job? One job that enqueues others? One job is simpler,
easier to reason about, and hits `job_timeout` first. Several jobs are more robust and make "one
`ScanRun`" harder to hold together. One job is the right answer for this week — be able to say what
would make it the wrong answer in week 6.

## Search for

- pipeline stages partial failure degrade
- saga vs single transaction long running job
- arq job enqueue from within job
- fan out fan in asyncio gather return_exceptions
- structured logging stage boundaries correlation id
- integration test end to end fixture docker
