# W1-10 · Docker target lab

**GitHub issue:** [#10](https://github.com/emad-anwer/tem-platform/issues/10)

**Owner:** Islam · **Reviewer:** Zyad · **Effort:** 4h · **Depends on:** nothing

Deliberately dependency-free — this is the parallel track when the #5→#6→#7 chain is blocking people.

## What

A separate compose profile (`just lab-up`) with four deliberately varied scan targets:

1. **nginx** with a recognizable server banner
2. **An older Apache** — different banner, different fingerprint
3. **A service on a non-standard port** — so port assumptions get caught
4. **A host with a self-signed TLS certificate carrying multiple SANs**

Must not start with the normal `just up`.

Then write `docs/target-lab.md` documenting the **expected ground truth**: exactly what a correct
scanner should discover on each target — ports, banners, certificate SANs, technologies.

## Expected outcome

- `just lab-up` starts the targets, `just lab-down` stops them
- `docs/target-lab.md` states what a correct scan finds

## Why this exists

This isn't a substitute for the approved scanning scope. It's the **test fixture** the week 4
scanner gets validated against. A live internet target changes underneath you and can't tell you
whether your scanner is wrong or the target moved. This one has known, documented answers.

Every hour spent here saves several in week 4 debugging.

## Search for

- Docker Compose profiles
- openssl self-signed certificate with SAN
- service banner grabbing
- nginx server_tokens
