# W3-09 · Staging: VPS, Compose overlay, secrets

**Owner:** unassigned — Islam if taken · **Reviewer:** Tasneem · **Effort:** 4h · **Depends on:** a provisioned VPS

> ## ⏸ Deferred — do not start this week
>
> **No staging box is being provisioned right now.** `DECISIONS.md` §7 keeps the VPS account and
> billing mentor-side, and that call has been made: staging moves out of week 3.
>
> The roadmap named this cut in advance — *"if it slips, cut staging to week 4 before cutting the
> pipeline spine"* — and it has been taken early, on purpose, rather than discovered on Thursday.
> Nothing else in week 3 depends on this task.
>
> The task stays written so it's ready the day a box exists. Until then, **if you have spare time,
> it goes to the pipeline spine, not here.**

## What

Get the stack running on a machine nobody has a laptop session on.

- **`compose.staging.yaml`** — an overlay on the existing compose file, not a fork of it. When
  somebody changes a service in `compose.yaml`, staging must inherit it
- **Secrets from the environment, never from a committed file.** Real values live on the box or in
  GitHub Actions secrets. Nothing secret goes in the repo, in the compose file, or in a log line
- `ENVIRONMENT=staging` and `REDIS_REQUIRED=true`. The config already anticipates both — in dev,
  Redis failure is tolerated; in staging it is not, because the worker's entire job is reading a
  queue
- **Expose only what has to be exposed.** The API, and Zitadel if the flow needs it. Postgres, Redis
  and the worker are not on the public internet. Check what the compose file publishes today
- The **target lab profile stays off**. It is a deliberately vulnerable environment and it belongs
  on a laptop behind a firewall, not on a public IP
- Volumes that survive a redeploy, so staging data isn't wiped every merge
- A short section in the PR: what runs where, which ports are open, and where secrets come from

## Expected outcome

The full stack — API, worker, Postgres, Redis, Zitadel — runs on the staging box. `/health` answers
from outside. A scan started through the staging API is executed by the staging worker.

## Think about

**What staging is for.** Not "a second dev environment" — it is the place where wrong assumptions
about your dev machine surface. Hostnames that only resolved because of Docker's local DNS.
`localhost` in a config that meant something different in a container. An issuer URL that was right
on your laptop and is wrong the moment anything external talks to Zitadel. Expect to find at least
two of those, and note them in the PR — and if W3-12 has already shipped by the time this is
picked up, that list is the section it is missing.

**Then the security question**, and take it seriously because this box has a public IP. What is
reachable from the internet right now? Not what you intended to expose — what `docker compose ps`
actually publishes. A Postgres port bound to `0.0.0.0` is found by scanners within hours, and we are
in the business of telling customers that.

## Search for

- docker compose override file multiple -f merge
- docker compose ports vs expose bind 127.0.0.1
- docker compose env_file environment precedence
- ufw docker published ports bypass firewall
- zitadel external domain tls configuration
- ssh hardening disable password authentication
