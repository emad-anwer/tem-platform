# API Conventions

**Authors:** Arwa Hazem, Tasneem Mohamed, Zyad Mohamed, Islam Abdelslam
**Owner:** Arwa Hazem · **Reviewer:** Zyad Mohamed

This document retroactively records a contract decision. Zyad (or the current mentor) must
confirm that the JSON:API and cursor-pagination conventions apply to every future endpoint,
including ASM and threat-intelligence endpoints, rather than only the tenant endpoints.

This document is the contract every endpoint must follow. If behaviour is not specified here,
ask on the issue before implementing — do not invent a local convention.

---

## REST maturity level

We target **Richardson Level 2**:

- Resources identified by URLs (`/tenants`, not `/getTenant`)
- HTTP verbs carry meaning (GET reads, POST creates, …)
- Status codes reflect outcome (201 for created, 404 for missing, …)

We **do not** target Level 3 (HATEOAS). Responses will not include hypermedia navigation links.
That is a deliberate scope choice for an eight-week backend program, not a rejection of REST.

---

## URL structure and versioning

All public endpoints live under a versioned prefix:

```
/api/v1/{resource}
/api/v1/{resource}/{id}
/api/v1/{resource}/{id}/{sub-resource}
```

| Rule | Example |
|---|---|
| Version in path | `/api/v1/tenants` |
| Lowercase paths | `/api/v1/scan_runs` not `/api/v1/ScanRuns` |
| Plural resource nouns | `/tenants`, `/findings`, `/targets` |
| No verbs in paths | `/tenants` not `/createTenant` or `/tenant/create` |
| Nested resources for ownership | `/api/v1/tenants/{tenant_id}/targets` |

### When to introduce `/api/v2`

A new major version is justified **only** for breaking contract changes, for example:

- Removing or renaming a response field that clients depend on
- Changing the meaning of an existing status code for the same request
- Changing authentication or tenancy resolution in a way that breaks existing clients

Non-breaking additions (new optional fields, new endpoints, new query parameters) stay in `v1`.
Deprecate old fields in documentation; do not silently change semantics.

---

## HTTP methods

We support **GET, POST, PATCH, DELETE**. We do **not** use PUT in v1.

| Method | Semantics | Safe | Idempotent | Request body |
|---|---|---|---|---|
| **GET** | Retrieve a resource or collection | Yes | Yes | No |
| **POST** | Create a new resource | No | No | Yes |
| **PATCH** | Partial update of an existing resource | No | No* | Yes |
| **DELETE** | Remove a resource | No | Yes | No |

\*PATCH is not strictly idempotent (two patches with different bodies produce different results).
Clients must not assume retrying a PATCH is safe unless documented for a specific endpoint.

We skipped PUT because none of our v1 resources require full replacement semantics. If a resource
needs replace-all behaviour later, discuss on an issue before adding PUT.

### Collection vs item routes

```
GET    /api/v1/tenants           # list
POST   /api/v1/tenants           # create
GET    /api/v1/tenants/{id}      # retrieve one
PATCH  /api/v1/tenants/{id}      # partial update
DELETE /api/v1/tenants/{id}      # delete
```

Actions that are not CRUD on a resource (e.g. `POST /api/v1/targets/{id}/scan`) are allowed when
they represent a **command on a resource**, but the path must still be noun-based — the verb is
the HTTP method, not a path segment like `/scanTarget`.

---

## Status codes

We use a fixed set. Handlers must not invent new codes for cases already covered here.

| Code | When we use it | Response body |
|---|---|---|
| **200 OK** | Successful GET, PATCH, or POST that returns the resource | Resource or wrapper JSON |
| **201 Created** | Successful POST that created a resource | Created resource JSON |
| **204 No Content** | Successful DELETE | Empty — no body |
| **400 Bad Request** | Malformed request: invalid JSON, wrong types, unknown query param | Error envelope |
| **401 Unauthorized** | Missing, invalid, or expired authentication | Error envelope |
| **403 Forbidden** | Authenticated, but not permitted for this tenant or role | Error envelope |
| **404 Not Found** | Resource does not exist, or caller must not know it exists | Error envelope |
| **409 Conflict** | Valid request that conflicts with current state (duplicate slug, etc.) | Error envelope |
| **422 Unprocessable Content** | Well-formed JSON that fails semantic/business validation | Error envelope |
| **429 Too Many Requests** | Rate limit exceeded | Error envelope + `Retry-After` header |
| **500 Internal Server Error** | Unexpected server fault | Error envelope |
| **503 Service Unavailable** | Dependency down (database unreachable on a data endpoint) | Error envelope |

Rules:

- **5xx = our fault.** Never use 5xx because the client sent bad input.
- **422 vs 400:** 400 when the request cannot be parsed or violates transport syntax; 422 when
  JSON parses but business rules fail (Pydantic `ValidationError` on a request model → 422).
- **404 vs 403:** when a resource exists but the caller lacks access, return **403**, not 404,
  unless revealing existence is itself a security concern (then 404 is acceptable — document which
  applies per resource on the issue).

### 401 vs 403

This distinction is fixed for the whole project:

| Code | Meaning | Typical causes |
|---|---|---|
| **401 Unauthorized** | *Who are you?* Authentication failed or is absent. | No `Authorization` header, expired JWT, invalid API key |
| **403 Forbidden** | *I know who you are; you can't do this.* Authorization failed. | Viewer role calling a delete endpoint, token valid but for a different tenant |

FastAPI mapping:

- Missing/invalid credentials → 401
- Valid credentials, insufficient permission → 403

### Success headers

| Situation | Required headers |
|---|---|
| **201 Created** | `Location: /api/v1/{resource}/{id}` — absolute or relative URI to the new resource |
| **429 Rate limited** | `Retry-After: <seconds>` |
| All JSON responses | `Content-Type: application/json` |

---

## Error envelope

We adopt **[RFC 9457 Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html)**.

Every error response uses `Content-Type: application/problem+json` and this shape:

```json
{
  "type": "https://tem-platform.dev/problems/not-found",
  "title": "Not Found",
  "status": 404,
  "detail": "Tenant with id '3fa85f64-5717-4562-b3fc-2c963f66afa6' does not exist.",
  "instance": "/api/v1/tenants/3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

| Field | Required | Description |
|---|---|---|
| `type` | Yes | URI identifying the problem type. Use `https://tem-platform.dev/problems/{slug}` |
| `title` | Yes | Short, stable summary (same for all errors of this type) |
| `status` | Yes | HTTP status code (must match the response status) |
| `detail` | Yes | Human-readable explanation specific to this occurrence |
| `instance` | Yes | Request path that triggered the error |

Optional extension fields (allowed by RFC 9457):

```json
{
  "type": "https://tem-platform.dev/problems/validation-error",
  "title": "Validation Error",
  "status": 422,
  "detail": "One or more fields failed validation.",
  "instance": "/api/v1/tenants",
  "errors": [
    { "field": "slug", "message": "must contain only lowercase letters, numbers, and hyphens" }
  ]
}
```

### Problem type registry (initial)

| Slug | Status | When |
|---|---|---|
| `bad-request` | 400 | Malformed request |
| `unauthorized` | 401 | Authentication failure |
| `forbidden` | 403 | Authorization failure |
| `not-found` | 404 | Resource not found |
| `conflict` | 409 | State conflict |
| `validation-error` | 422 | Semantic validation failure |
| `rate-limited` | 429 | Too many requests |
| `internal-error` | 500 | Unexpected server error |
| `service-unavailable` | 503 | Dependency unavailable |

Implementation lives in W1-08 (error envelope and exception handlers). Endpoints must not craft
ad-hoc error JSON — raise typed exceptions and let the global handler format the response.

### Why RFC 9457

- Industry-standard shape; clients and tools recognize it
- FastAPI/Starlette can implement it once in middleware/exception handlers
- Extension fields (`errors` array) cover validation without a custom envelope
- Rejected alternative: a bespoke `{ "error": "...", "code": "..." }` envelope — less interoperable
  and we'd be documenting a new format nobody else uses

---

## Resource and collection responses

Successful resource responses use a JSON:API-style document. A single resource has `data` with
its resource `type`, server-generated `id`, and domain fields under `attributes`:

```json
{
  "data": {
    "type": "tenants",
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "attributes": {
      "name": "Acme Corp",
      "slug": "acme-corp",
      "is_active": true,
      "created_at": "2026-08-25T09:00:00Z"
    }
  }
}
```

Collection responses use the same resource objects in a `data` array and include pagination
links. Do not introduce an `items`/`pagination` envelope.

```json
{
  "data": [
    {
      "type": "tenants",
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "attributes": { "name": "Acme Corp", "slug": "acme-corp" }
    }
  ],
  "links": {
    "self": "/api/v1/tenants?size=20",
    "next": "/api/v1/tenants?size=20&cursor=opaque-token"
  }
}
```

`links.next` is `null` on the final page. Resource `type` values are stable plural nouns, `id`
values are UUID strings, and resource fields belong in `attributes` rather than beside `id`.

## Pagination

List endpoints use **cursor pagination**. The HTTP API accepts `size` and `cursor`; the repository
method uses the equivalent internal names `limit` and `cursor` and returns `(items, next_cursor)`.

### Query parameters

| Param | Type | Default | Max | Description |
|---|---|---|---|---|
| `size` | integer | `20` | `100` | Number of resources to return |
| `cursor` | string | omitted | — | Opaque position returned by the previous page's `links.next` URL |

Requests with `size > 100` return **400** with a validation error. Clients must treat cursors as
opaque: they must not decode, edit, or manufacture them. A cursor is valid only with the same
resource collection and ordering that produced it.

The repository fetches `limit + 1` rows to determine whether another page exists. It returns at
most `limit` rows and sets `next_cursor` to an encoded ordering key when more rows remain;
otherwise `next_cursor` is `None`. The tenant implementation orders by `(name, id)` to keep the
cursor position deterministic.

### Why cursor pagination and JSON:API (Option B)

Cursor pagination was chosen over offset pagination because findings, events, and other module
data can change frequently between requests. Offsets can skip or repeat records when rows are
inserted or removed ahead of the current offset; a cursor continues from a deterministic ordered
position and avoids a potentially expensive count query. The same approach also works as the
collections grow beyond the initial tenant-sized data set.

JSON:API was adopted to give every endpoint a consistent document shape, explicit typed resource
identification (`type` and `id`), and a predictable path for future integrations that need to
discover and handle different resource types. This is a contract decision for future endpoints,
not a tenant-specific response style.

---

## Filtering and sorting

Collection endpoints accept filters and sort order as **query parameters**.

### Filtering

```
GET /api/v1/targets?status=active&tenant_id=3fa85f64-5717-4562-b3fc-2c963f66afa6
```

| Rule | Example |
|---|---|
| Exact match by default | `?status=active` |
| Multiple values = OR within one field | `?status=active,pending` (document per endpoint if supported) |
| Unknown filter param on an endpoint | **400** — fail loudly, do not silently ignore |
| Filter names match field names | `created_at`, not `createdAt` or `CreatedAt` |

### Sorting

```
GET /api/v1/findings?sort=-severity,created_at
```

| Rule | Example |
|---|---|
| `sort` parameter, comma-separated fields | `?sort=-created_at,name` |
| `-` prefix = descending | `?sort=-created_at` |
| No prefix = ascending | `?sort=name` |
| Default sort | Document per endpoint; if unspecified, default is `-created_at` (newest first) |

---

## Representation conventions

### Field naming

**snake_case** everywhere in JSON request and response bodies.

```json
{ "tenant_id": "...", "created_at": "2026-08-25T09:00:00Z", "is_active": true }
```

Not `tenantId`, not `CreatedAt`. Query parameters follow the same rule.

### Timestamps

| Rule | Value |
|---|---|
| Format | ISO 8601 |
| Timezone | **UTC always** |
| Serialization | Suffix with `Z` — e.g. `"2026-08-25T09:00:00Z"` |
| Precision | Seconds; fractional seconds allowed if the source has sub-second precision |
| Null | Use `null` for absent/unknown timestamps, not empty strings |

Python: serialize with timezone-aware UTC datetimes. Never return naive local times.

### Identifiers

| Rule | Value |
|---|---|
| Type | **UUID version 4** |
| JSON representation | **String** — e.g. `"3fa85f64-5717-4562-b3fc-2c963f66afa6"` |
| Path parameters | Same string form |
| Generation | Server-generated on create; clients must not supply `id` on POST |

### Null vs omitted

- **Optional fields** absent from a PATCH body = leave unchanged
- **Optional fields** explicitly set to `null` in PATCH = clear the value (if the field is nullable)
- Responses include nullable fields as `null` when empty, not omitted, unless the field is
  genuinely inapplicable (document per resource)

### Booleans, enums, and strings

- Booleans: JSON `true` / `false`, never `"true"` strings
- Enums: lowercase snake_case string values — `"active"`, `"scan_pending"`
- Slugs and codes: lowercase, hyphen-separated where applicable — `"acme-corp"`

---

## Idempotency

| Operation | Safe to retry? | Notes |
|---|---|---|
| **GET** | Yes | Safe and idempotent by definition |
| **DELETE** | Yes | Deleting an already-deleted resource returns **404** (or **204** if we adopt "delete is success regardless" — we use **404** for unknown IDs) |
| **PATCH** | Caution | Retries may apply the same change twice; design patches to be safe where possible (e.g. setting `status=active` when already active is a no-op → 200) |
| **POST** | No | Retries may create duplicates → use **409 Conflict** on unique constraints |
| **POST (commands)** | No | e.g. enqueue scan — document per endpoint; future idempotency keys out of scope for v1 |

Unique constraints (tenant slug, email) must return **409 Conflict**, not 500, on duplicate POST.

---

## Multi-tenancy (preview for endpoint authors)

Detailed auth is week 2, but conventions assume:

- Every tenant-scoped resource belongs to exactly one tenant
- List endpoints return only the authenticated tenant's data unless the caller is a platform admin
  (future — not v1)
- Cross-tenant access attempts return **403**, not empty lists

Tenant-scoped paths may use `/api/v1/tenants/{tenant_id}/…` or resolve tenant from the token —
pick one pattern per resource family and document on the issue. Do not mix both for the same
resource type.

---

## OpenAPI and documentation

- FastAPI auto-generates OpenAPI from Pydantic models — models must match this document
- Enum fields use `json_schema_extra` or Python `Enum` so Swagger shows allowed values
- Tag endpoints by module: `tenants`, `health`, `asm`, etc.
- Example values in schemas should use UUID strings and UTC timestamps as shown above

---

## Checklist for new endpoints

Before opening a PR for any endpoint (from W1-07 onward):

- [ ] Path under `/api/v1/`, plural noun, no verb segments
- [ ] Correct HTTP method and status code from the tables above
- [ ] 201 + `Location` header on create
- [ ] 204 empty body on delete
- [ ] Errors via RFC 9457 problem details — no custom error shapes
- [ ] List endpoints use JSON:API `data` resources with cursor pagination (`size`, `cursor`, and `links.next`)
- [ ] snake_case fields, UUID string IDs, UTC ISO 8601 timestamps
- [ ] 401 vs 403 used correctly
- [ ] Tests cover success path and at least one error path

---

## References

- [RFC 9110 — HTTP Semantics (status codes)](https://www.rfc-editor.org/rfc/rfc9110.html#name-status-codes)
- [RFC 9457 — Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html)
- [Richardson Maturity Model](https://martinfowler.com/articles/richardsonMaturityModel.html)
