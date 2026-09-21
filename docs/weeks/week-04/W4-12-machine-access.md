# W4-12 · Machine access: Zitadel service users

**Owner:** unassigned — Islam if taken · **Reviewer:** Tasneem · **Effort:** 4h · **Depends on:** —

> **Optional. Do not start unless Wednesday comes in clean.** Nothing this week depends on it and
> nothing in week 5 does until feed ingestion needs a scheduled caller.

## What

ADR-0002 §9 decided this in week 2: machine-to-machine access uses **Zitadel service users with the
client credentials grant**, not our own API keys. The reasoning is already written down — one token
format, one validation path, one place that revokes access — so this task is implementation, not
design.

- Create a service user in Zitadel and grant it a role from the existing matrix. The bootstrap
  script from week 2 is where this belongs, so a clean clone still works end to end
- Obtain a token via **client credentials**, and confirm the existing `verify_token` path validates
  it with no changes. If it needs changes, that is the finding — ADR-0002's central claim is that
  human and machine tokens are the same shape, and this is the first time anyone has checked
- Confirm a machine token carries a tenant and a role that `require_permission` already understands.
  A machine principal that lands with no tenant must fail closed, exactly like a human one
- Document how a caller gets a token, in `docs/auth.md` alongside the human flow

Tests:

- A service-user token authenticates and is scoped to its tenant
- A machine principal with no tenant claim is rejected, not defaulted
- A service user without the required role gets `403`, not `500`

**Credentials never enter the repository.** Not in a test fixture, not in a `.env.example`, not in a
comment. The bootstrap script generates them; the runbook says where they go.

## Expected outcome

A script with no browser and no human can call `POST /api/v1/targets` with a token it obtained
itself, and gets the same authorization decisions a human would.

## Think about

ADR-0002 claims humans and machines produce the same token shape and the same `Principal`. That is a
strong claim and nobody has tested it. If it turns out to be false, the finding is worth more than
the feature — write it up and amend the ADR rather than bending the code to preserve a sentence.

Think about token lifetime. A human's access token being short-lived is fine because there is a
refresh flow and a browser. A cron job at 3am has neither. Zitadel can issue longer-lived tokens for
service users; that is a trade-off between convenience and blast radius, and it is a decision, not a
setting.

## Search for

- zitadel service user client credentials grant
- oauth2 client credentials machine to machine
- private key jwt client authentication
- service account token lifetime rotation
- jwt audience claim validation machine token
