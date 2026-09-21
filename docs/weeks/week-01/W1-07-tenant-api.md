# W1-07 · Tenant API endpoints

**GitHub issue:** [#7](https://github.com/emad-anwer/tem-platform/issues/7)

**Owner:** Arwa · **Reviewer:** Zyad · **Effort:** 4h · **Depends on:** #6, #2

## What

| Method | Path | Success | Notes |
|---|---|---|---|
| `POST` | `/api/v1/tenants` | `201` + `Location` header | create, with validation |
| `GET` | `/api/v1/tenants` | `200` | list, paginated per #2 |
| `GET` | `/api/v1/tenants/{id}` | `200` | fetch one |

Pydantic request and response schemas. Slug format validation.

**Error cases, all returned in the agreed envelope:**
- `409 Conflict` — duplicate slug
- `404 Not Found` — unknown ID
- `422` — well-formed request that fails validation

## Expected outcome

Endpoints work in Swagger and follow `docs/api-conventions.md` **exactly** — this is the first
test of whether the team's own conventions survive contact with real code.

If you find yourself wanting to deviate from the conventions, that's not a reason to deviate. It's
a reason to go back to #2 and change the document, with the team.

## Two things to get right

**`201` and the `Location` header.** A creation response says where the new thing lives. Most
tutorials skip this; RFC 9110 doesn't. Do it properly.

**The slug is validated in the Pydantic schema *and* constrained unique in the database.** Both.
If you think one of those is redundant, work out why it isn't before you open the PR — you'll be
asked.

## Search for

- FastAPI response_model status_code
- HTTP 201 Created Location header
- Pydantic v2 field_validator
- HTTP 409 vs 422
