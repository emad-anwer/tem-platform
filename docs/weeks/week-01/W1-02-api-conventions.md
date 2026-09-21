# W1-02 · API conventions huddle and written decision

**GitHub issue:** [#2](https://github.com/emad-anwer/tem-platform/issues/2)

**Owner:** Arwa · **Reviewer:** all four · **Effort:** 45min meeting + 2h writing · **Depends on:** nothing

## What

A 45-minute session, all four present, to decide the API conventions **before** anyone writes an
endpoint. Then write the decision up as `docs/api-conventions.md`.

### REST conventions to settle

- **Resource naming** — plural nouns, no verbs in paths. `/tenants`, never `/getTenant` or
  `/tenant/create`. The HTTP method *is* the verb
- **Method semantics** — `GET` safe and idempotent, `POST` creates, `PUT` replaces the whole
  resource, `PATCH` updates part of it, `DELETE` removes. Decide which we support and hold to the
  meanings
- **Status codes** — the exact set we use, and what each means in this API:
  - `200` retrieved · `201` created, with a `Location` header · `204` deleted, no body
  - `400` malformed request · `401` not authenticated · `403` authenticated but not allowed
  - `404` not found · `409` conflict · `422` well-formed but semantically invalid
  - `429` rate limited · `5xx` our fault, never the client's
  - **401 vs 403 trips everyone up.** Settle it now, in writing
- **Versioning** — `/api/v1` in the path. Also decide what would justify a `v2`, so nobody
  breaks v1 casually
- **Idempotency** — which endpoints are safe to retry, and which aren't

### Representation conventions to settle

- **Error envelope** — one shape for every error the API returns. Consider
  [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457.html): adopt it, or reject it
  for a stated reason
- **Pagination** — limit/offset or cursor, and what the response wrapper looks like
- **Collections** — filtering and sorting as query parameters. Naming and defaults
- **Field naming** — snake_case throughout, presumably, but say so
- **Timestamps** — format and timezone. (UTC, ISO 8601 is the boring correct answer)
- **IDs** — UUID version, and whether they're exposed as strings

## Expected outcome

`docs/api-conventions.md` merged, and every endpoint from #7 onward follows it.

## Read before the meeting

- **[RFC 9110 — HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html)**, status code
  section only. This is the actual specification, not a blog post's interpretation of it. Fifteen
  minutes here settles most of the arguments before they start
- **[RFC 9457 — Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html)** —
  a real standard for the error envelope. Adopt it or reject it deliberately
- **Richardson Maturity Model** — a short read on what "RESTful" actually means in levels. Decide
  which level we're targeting and be honest that level 3 (HATEOAS) is probably not it

## Why this matters more than it looks

This is the highest-leverage 45 minutes of the entire eight weeks. Four engineers agreeing one
error shape and one status-code policy now is the difference between a coherent API in week 6 and
four incompatible ones.

Argue it out. Don't wait for the mentor to decide it.

## Search for

- RFC 9110 HTTP status codes
- RFC 9457 problem details
- Richardson Maturity Model
- REST API resource naming conventions
- cursor vs offset pagination
- HTTP 401 vs 403 difference
