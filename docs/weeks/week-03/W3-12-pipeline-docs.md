# W3-12 · Pipeline documentation

**GitHub issue:** [#75](https://github.com/emad-anwer/tem-platform/issues/75)

**Owner:** Islam · **Reviewer:** Tasneem · **Effort:** 2h · **Depends on:** #72, #74

In week 5 somebody adds a threat-intelligence job to this pipeline. They will not have been in
Sunday's huddle and they will not read W3-04 to work out how. Write for them.

> This was the staging runbook until staging was deferred. The operational half went with it; the
> pipeline half is the part week 4 actually needs, and it was always the more useful of the two.

## What

**`docs/pipeline.md`** — one document, short. Short is the requirement, not the concession.

- **The path from `POST /targets/{id}/scans` to a persisted finding**, in one diagram or one
  paragraph. Which process does what, and where the handoff is
- **How a module adds a new job.** The registration, the context, the state transitions it's
  responsible for, the things the framework does for it. This is the section with the longest
  half-life — everything else in this doc describes what exists, and this one tells the next person
  how to extend it
- **The `ScanRun` states** and what moves between them, including the transitions nobody enqueues
- **The finding fingerprint rule** from ADR-0003, what it means for duplicates, and why
  `first_seen_at` never moves
- **How to read worker logs** and find one job's lines among all the others
- **How to find out why a scan is stuck in `running`** — the question most likely to be asked in
  week 4, by someone who wasn't here this week
- **What to do when crt.sh is down**, and how to confirm that's what's happening rather than a bug

Link it from the repo README. A document nobody can find is a document nobody wrote.

## Expected outcome

Tasneem starts week 4 from this document rather than from your memory. That is the acceptance test
and you can actually run it: hand it to her, ask her to explain why a scan is stuck, and say nothing.

## Think about

The failure mode of documentation like this is that it describes the happy path — the one thing
nobody needs a document for. Everything in yours should be something that went wrong this week, or
something you had to work out by reading someone else's code.

So: what did you actually get stuck on between Monday and Thursday? What did you look up twice?
Which command did you find by trial and error? That list *is* the document. If you can't remember,
you wrote this too late — write it while it still annoys you.

Write for someone who is debugging, not someone who is studying. Commands they can paste, in the
order they'd need them.

## Search for

- diataxis documentation framework explanation vs how-to
- mermaid sequence diagram markdown github
- docker compose logs filter service since
- structlog json logs querying jq
- architecture documentation c4 model level 2
