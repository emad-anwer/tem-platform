# How we work

## Branches

```
w1/tenant-api          # week + short description
w2/jwt-auth
fix/migration-rollback
```

Branch off `main`. Keep branches short-lived — if it's been open three days, it's too big.

## Pull requests

**One task, one PR.** If your PR needs the word "and" to describe it, split it.

A PR description answers three questions:
1. **What** does this change?
2. **Why** this approach and not another?
3. **How** did you verify it works?

Link the issue it closes: `Closes #12`.

**Draft PRs are encouraged.** Open one early if you want eyes on a direction before you finish.

## Review

- **Every PR needs one approval from a teammate** before merge
- Add the **`needs-mentor-review`** label if the PR touches:
  - database schema
  - authentication, authorization, or tenant isolation
  - anything crossing a module boundary
  - a dependency added to `pyproject.toml`
- Review is about substance, not style — `ruff` handles style, so don't spend review comments on it
- **Reviewing is real work.** It's in your weekly hours. A rubber-stamp approval helps nobody

### Reviewing well

Ask questions rather than issuing orders. "What happens if this is called twice?" teaches more
than "add idempotency here." If you don't understand something, that itself is review feedback —
code a teammate can't follow is code the team can't maintain.

## Definition of done

A task is done when **all** of these are true:

- [ ] Code merged to `main`
- [ ] Tests written and passing (from week 2, CI enforces this)
- [ ] `ruff check` and `ruff format` clean
- [ ] Migration included if the schema changed, and the downgrade path works
- [ ] Docs updated if behaviour or setup changed
- [ ] Reviewed and approved by a teammate

"It works on my machine" is not done. From week 3, "it works on staging" is.

## Weekly rhythm

**Sunday–Thursday.** Sunday stand-up (kickoff), Tuesday stand-up (blockers), Thursday demo.

The **weekly lead** rotates. That week they run stand-up, own integration, and are the first
person a blocked teammate talks to.

| Wk 1 | Wk 2 | Wk 3 | Wk 4 | Wk 5 | Wk 6 | Wk 7 | Wk 8 |
|---|---|---|---|---|---|---|---|
| Zyad | Arwa | Islam | Tasneem | Tasneem | Islam | Arwa | Zyad |

## When you're stuck

Timebox it to **45 minutes**. Then ask — in the team channel, not privately, so the answer helps
everyone.

A good question shows your work:

> "I'm trying to X. I expected Y, but I'm getting Z. I've checked A and B, and I think the cause
> might be C. Here's the error: …"

A question that just says "it doesn't work" will get "what have you tried?" and cost you another
hour.
