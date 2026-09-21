# W3-01 · Pipeline design huddle and ADR-0003

**GitHub issue:** [#66](https://github.com/emad-anwer/tem-platform/issues/66)

**Owner:** Islam · **Reviewer:** all four + mentor · **Effort:** 2h + 45min meeting · **Depends on:** —

🔑 This one gates the week. **It must merge Sunday** — W3-02, W3-03 and W3-04 all start from it, and
three people stall Monday morning if it doesn't.

You are designing the contract that four modules plug into for the next five weeks. ASM is the only
producer you can see today. It is not the one you're designing for.

## What

Meet for 45 minutes. Decide, argue, then write it down.

**The domain questions:**

- What is a `Target`? A domain, an IP, a CIDR range, an app store listing, a brand name? One table
  with a `kind`, or separate tables? Whatever you choose has to hold a dark web keyword in week 6
- What is a `ScanRun`? What does it record beyond start and finish — which source ran, how many
  findings, why it failed?
- What is a `Finding` such that ASM, threat intelligence, dark web monitoring and brand protection
  all fit in it **without a schema change**? Where does the module-specific detail live?
- **What makes two findings the same finding?** This is the hardest question in the meeting and
  W3-08 implements whatever you decide. `subdomain.example.com` found on Monday and again on Tuesday
  is one finding seen twice, not two findings
- Who decides severity — the module that produced the finding, or the platform?
- What are the states of a `ScanRun` and which transitions are legal?

**The API question you also have to settle.** The tenant endpoints currently return a JSON:API
document with cursor pagination. `docs/api-conventions.md` — which you wrote and merged in week 1 —
mandates a flat `items` / `pagination` envelope with limit/offset. Both are in `main`. This is
[#52](https://github.com/emad-anwer/tem-platform/issues/52), and W3-11 adds four more endpoints
that will bake in whichever answer wins. Pick one. Amend the convention doc or change the code, but
the repository stops contradicting itself this week.

Then write **`docs/adr/0003-pipeline-contract.md`** in the same form as ADR-0002: context, the
options you actually considered, the decision, the consequences, and **what you rejected and why**.
An ADR that only records the winner is a note, not a decision record.

## Expected outcome

`docs/adr/0003-pipeline-contract.md` merged **Sunday**, and `docs/api-conventions.md` either amended
or obeyed — but no longer contradicted by the code.

W3-02 can write the migration straight from the ADR without asking anyone a question.

## Think about

The trap is designing `Finding` around the only thing you can currently produce: a subdomain. It
will fit beautifully. Then week 5 arrives with an IOC that has a confidence score and a source feed,
week 6 arrives with a leaked credential that has a breach date and a paste URL, and each one wants
three new columns.

So before you commit to a shape, write out — on paper, in the meeting — what these four look like in
your table:

- `admin.example.com` resolves to `203.0.113.10` *(ASM, this week)*
- `1.2.3.4` appears in a botnet C2 feed with confidence 0.8 *(threat intel, week 5)*
- `admin@example.com` appears in a credential dump posted 2026-08-14 *(dark web, week 6)*
- An app store listing impersonating your customer's brand *(brand protection, week 7)*

If your answer needs a new column for any of them, the shape is wrong. If your answer is "a JSONB
blob for everything", ask what you can still query, sort and alert on.

The second thing worth arguing about: `Target`, `ScanRun` and `Finding` go in **`core`**, not in
`modules/asm`. Make sure everyone can say why. The dependency rule from week 1 — `modules → core`,
never `modules → modules` — is what forces it, and the alternative is four separate pipelines by
week 7.

## Search for

- domain model design bounded context
- security finding data model normalization
- polymorphic vs single table inheritance sql
- jsonb column indexing postgres when to use
- architecture decision record template
- deduplication key event identity
