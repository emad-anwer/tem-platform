# W2-05 · Zitadel in Compose and an idempotent bootstrap

**GitHub issue:** [#35](https://github.com/emad-anwer/tem-platform/issues/35)

**Owner:** Zyad · **Reviewer:** Islam · **Effort:** 5h · **Depends on:** #32

> The mentor has already committed a **working** `docker-compose` service and a notes file. Start
> from that. Your job is not to get Zitadel running for the first time — it's to make it
> reproducible, bootstrapped, and documented. If you find yourself debugging a first-boot failure
> for more than 30 minutes, that's a mentor question, not a you question.

## What

Make a fresh clone able to run the whole stack, including identity, with one command.

- Zitadel service in `docker-compose.yml` with **its own database** (its schema is not yours and
  must never be mixed into your migrations)
- A masterkey and all secrets read from `.env`, with `.env.example` updated. Nothing secret
  committed, ever
- TLS disabled for local dev, and a comment saying so and saying why that's local-only
- A **bootstrap script** that creates: the project, the application, the project roles from
  ADR-0002, and one dev organisation with one dev user
- The bootstrap is **idempotent**. Running it twice is a no-op, not an error and not a duplicate.
  Someone will run it twice on Wednesday
- `just up` brings everything up healthy; `just zitadel-bootstrap` is safe to re-run
- Health checks and `depends_on: condition: service_healthy`, so the API doesn't start talking to
  an IdP that isn't listening yet

## Expected outcome

`git clone && cp .env.example .env && just up && just zitadel-bootstrap` gives a working local
environment on a machine that has never seen this project. Test that claim on a teammate's laptop
before you open the PR — not on yours.

## Think about

**The issuer trap.** The `iss` claim in every token is whatever Zitadel thinks its external URL is.
Your API container reaches Zitadel by its compose service name; your browser reaches it on
`localhost`. If those two disagree, tokens minted through the browser fail validation inside the
API — and the error will look like a bug in W2-04's code, which it isn't. Work out what the issuer
must be **before** you configure it, and write the answer in the notes file so the next person
doesn't lose an afternoon.

Second: "idempotent" is doing real work in this task. What does your script do when the project
exists but one role is missing? Crash, skip, or reconcile? One of those three is right.

## Search for

- zitadel docker compose self hosting postgres
- zitadel masterkey ZITADEL_EXTERNALDOMAIN externalsecure
- zitadel first instance bootstrap service user pat
- zitadel management api create project role grant
- docker compose depends_on service_healthy healthcheck
- idempotent provisioning script
