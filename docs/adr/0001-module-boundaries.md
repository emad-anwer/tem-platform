# ADR 0001: Module Boundaries

**Date:** 2026-08-28

## Decision

We are keeping this backend as a **modular monolith with hard module boundaries**.

That means:

- A **module** is a self-contained business area under `src/app/modules/<name>/`.
- `core` is the shared platform layer under `src/app/core/`.
- Modules may depend on `core`.
- Modules must never import each other directly.
- When one module genuinely needs another module’s capability, it must do so through an interface or contract defined in `core`, not by reaching into the other module’s implementation.

We chose this over a looser shared-code approach because the project needs real separation of concerns more than it needs convenience. We are building a team that can still reason about ASM, Threat Intel, Brand Protection, and Dark Web as distinct business areas in week 6, not one tangled codebase where every change leaks across the whole tree.

## Why this decision

The team has enough scope to build four vertical slices, but not enough time to afford accidental architecture. Direct cross-imports are fast in week 1 and expensive by week 6: they create hidden coupling, make testing harder, and turn “add one field” into “touch three modules and hope nothing breaks.”

We want the opposite:

- module ownership that is obvious from the path
- changes that stay local unless they truly cross a boundary
- communication that is explicit enough to review
- shared primitives that are stable enough to reuse

The goal is not maximal abstraction. The goal is to make it difficult to write the wrong dependency by accident.

## What a module is

A module is the unit of business ownership in this codebase. A module contains the code needed to deliver one domain slice end to end:

- `route.py` for HTTP endpoints exposed by the module
- `api.py` for the module’s public interface to the rest of the application
- `service.py` for business logic and orchestration
- `repository.py` for database access
- `models.py` for ORM models and persistence shape
- `schemas.py` for request and response validation

Example modules in this repo are `asm`, `intel`, `brand`, and `darkweb`.

A module may also contain internal helpers, but anything that is intended for other modules to use must be declared in the module’s `api.py`, not imported from an internal file by convention or convenience.

## What `core` owns

`core` owns the things that are shared infrastructure, shared domain primitives, or shared contracts that must outlive any single module.

That includes:

- application bootstrap and composition
- configuration
- database/session plumbing
- Redis plumbing
- logging
- health checks
- shared error handling
- shared tenancy primitives
- cross-module interfaces and abstract contracts

`core` exists so shared concerns have one home. It is the place where we define the shape of collaboration between modules.

### What `core` must never own

`core` must never become a dumping ground for business logic.

It must not own:

- module-specific use cases
- module-specific repositories
- module-specific routes
- module-specific database models
- vendor integrations that only one module uses
- “just for now” copies of module code

If something only matters to ASM, it does not belong in `core`. If `core` starts to know that ASM fetches asset intelligence from one vendor while Threat Intel normalizes CVE feeds from another, we have already lost the boundary.

`core` can define the interface that both modules use. It cannot become the implementation of either module.

## Dependency rule

The dependency direction is one way:

- modules may depend on `core`
- modules may not depend on each other

This is the rule that keeps the monolith modular.

The practical effect is:

- `src/app/modules/asm/...` can import `src/app/core/...`
- `src/app/modules/intel/...` can import `src/app/core/...`
- `src/app/modules/asm/...` must not import `src/app/modules/intel/...`
- `src/app/modules/intel/...` must not import `src/app/modules/asm/...`

We rejected peer-to-peer module imports because they create a hidden graph that only the original author can navigate. The first time ASM reaches into Threat Intel directly, the next dependency arrives by imitation, and soon the module tree is only cosmetic.

## How modules communicate

When a module genuinely needs another module’s capability, it does not import the other module’s service or repository directly.

Instead, the consuming module depends on an **interface defined in `core`**:

- a `Protocol`
- an abstract base class
- a typed callable contract
- a shared DTO or event shape

The producing module provides the implementation, and composition happens at the application boundary.

This gives us three benefits:

- the caller depends on a stable contract, not an implementation detail
- the provider can change its internals without breaking consumers
- tests can substitute fakes cleanly

We rejected direct imports because they couple the caller to the callee’s package layout and make reuse feel easy at the exact point where we should be making it explicit.

## Folder layout

The folder layout is intentionally split by responsibility:

```text
src/app/
  core/
  modules/
    asm/
    intel/
    brand/
    darkweb/
```

Each module follows the same internal shape:

```text
src/app/modules/<module>/
  api.py
  route.py
  service.py
  repository.py
  models.py
  schemas.py
```

This shape exists for one reason: it makes the boundary visible without opening files.

- `modules/` says “this is business capability”
- `core/` says “this is shared platform code”
- per-module subfolders keep code local to the domain it serves
- consistent filenames make it easy to find the right layer in any module

We rejected a flatter shared package because “easy to import” quickly becomes “easy to couple.” We also rejected a deeper architecture with many subpackages per layer because it would be too heavy for the size of the team and the duration of the program.

## Worked example

### The violation

Suppose ASM needs CVE context while scanning an asset. A boundary violation would look like this:

```python
# src/app/modules/asm/service.py
from app.modules.intel.service import enrich_with_cves

def build_asset_report(asset_id: str) -> AssetReport:
    cves = enrich_with_cves(asset_id)
    ...
```

This is wrong because ASM now depends on Intel’s internal service. If Intel changes its service signature, ASM breaks. If Intel’s service needs a different repository shape, ASM inherits that churn even though it does not own the logic.

### The fix

Define the capability in `core`, then let Intel implement it:

```python
# src/app/core/contracts.py
from typing import Protocol

class CVEEnrichmentPort(Protocol):
    def enrich(self, asset_id: str) -> list[str]: ...
```

```python
# src/app/modules/intel/service.py
from app.core.contracts import CVEEnrichmentPort

class IntelCVEEnricher:
    def enrich(self, asset_id: str) -> list[str]:
        ...
```

```python
# src/app/modules/asm/service.py
from app.core.contracts import CVEEnrichmentPort

class ASMService:
    def __init__(self, cve_enricher: CVEEnrichmentPort) -> None:
        self._cve_enricher = cve_enricher

    def build_asset_report(self, asset_id: str) -> AssetReport:
        cves = self._cve_enricher.enrich(asset_id)
        ...
```

Now ASM depends on the contract, not the Intel implementation. Intel remains free to change how it queries feeds, stores data, or batches lookups, as long as it still satisfies the contract.

That is the trade-off we accept:

- we spend a little more effort defining interfaces up front
- we gain much better testability and far less accidental coupling later

## What this means in practice

1. If the code is part of one business capability, keep it inside that module.
2. If the code is shared across modules, move the shared shape into `core`.
3. If one module needs another module’s behavior, define the dependency in `core` and inject the implementation.
4. If you are about to import from another module, stop and ask whether you are depending on a contract or on an implementation accident.

The test for a good boundary is simple: if ASM can get CVE data from Threat Intel in week 6 without ASM knowing anything about Threat Intel’s internals, the architecture is working.

## Consequences

Positive:

- module ownership stays clear
- refactors stay local
- tests can isolate business logic cleanly
- the team can work in parallel without stepping on each other

Negative:

- a little more upfront design work
- some simple calls take an extra interface or adapter
- composition is slightly more explicit than direct imports

We accept those costs because they are smaller than the cost of a growing web of module-to-module imports.

