"""Tests for the run-to-run diff logic in FindingRepository.persist_discovery_run().

Covers the scenarios mandated by the issue:
- First run → every finding is `new`, nothing raises.
- Two runs, no change → everything `unchanged`, times_seen at 2.
- A finding absent from run 2 → `resolved`, and *nothing else* is.
- A previously-resolved finding returns → `reappeared` with original first_seen_at.
- A port scan does NOT resolve subdomain findings — the cross-kind correctness fix.
- Previous *failed* run is skipped; diff is against the last *successful* run.
- Two tenants with identical fingerprints diff independently.
"""

from __future__ import annotations

import uuid

from app.core.auth.context import set_current_principal
from app.core.auth.principal import Principal, Role
from app.core.fingerprint import FindingKind
from app.core.repository import (
    FindingRepository,
    ScanRunFindingRepository,
    ScanRunRepository,
    TargetRepository,
)


def _owner(tenant_id) -> Principal:
    return Principal(user_id="test-owner", tenant_id=tenant_id, role=Role.OWNER)


async def _make_target(session, *, tenant_id, name: str):
    return await TargetRepository(session, tenant_id=tenant_id).create(
        kind="domain",
        value=name,
        value_normalized=name,
        is_active=True,
    )


async def _make_run(session, *, tenant_id, target_id) -> object:
    return await ScanRunRepository(session, tenant_id=tenant_id).create(
        target_id=target_id, max_attempts=3
    )


async def _succeed_run(session, *, tenant_id, run) -> object:
    repo = ScanRunRepository(session, tenant_id=tenant_id)
    run = await repo.claim_for_job(run.id, job_id=str(uuid.uuid4()))
    return await repo.succeed(run.id)


def _item(
    target_id,
    *,
    run_id,
    hostname: str,
    kind: FindingKind = FindingKind.SUBDOMAIN,
    details: dict | None = None,
):
    """Build a single finding dict for upsert_discovery_batch / persist_discovery_run."""
    item = {
        "target_id": target_id,
        "run_id": run_id,
        "kind": kind,
        "value": hostname,
        "severity": "info",
    }
    if details is not None:
        item["details"] = details
    return item


def _counts(snapshots) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in snapshots:
        counts[s.classification] = counts.get(s.classification, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Test: first run → all new, nothing raises
# ---------------------------------------------------------------------------


async def test_first_run_all_findings_are_new(db_session, two_tenants):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    target = await _make_target(
        db_session, tenant_id=tenant_a.id, name="first-run.example.com"
    )
    run = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)

    findings_repo = FindingRepository(db_session, tenant_id=tenant_a.id)
    items = [
        _item(target.id, run_id=run.id, hostname=h)
        for h in ["a.first-run.example.com", "b.first-run.example.com"]
    ]
    await findings_repo.persist_discovery_run(
        target_id=target.id,
        run_id=run.id,
        items=items,
        kinds={FindingKind.SUBDOMAIN},
    )

    run_findings = await ScanRunFindingRepository(
        db_session, tenant_id=tenant_a.id
    ).list_for_run(run.id)

    counts = _counts(run_findings)
    assert counts == {"new": 2}, f"Expected all new, got {counts}"


# ---------------------------------------------------------------------------
# Test: two identical runs → all unchanged, times_seen = 2
# ---------------------------------------------------------------------------


async def test_two_identical_runs_all_unchanged(db_session, two_tenants):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    target = await _make_target(
        db_session, tenant_id=tenant_a.id, name="unchanged.example.com"
    )
    run1 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)

    findings_repo = FindingRepository(db_session, tenant_id=tenant_a.id)
    hostnames = ["x.unchanged.example.com", "y.unchanged.example.com"]
    items1 = [_item(target.id, run_id=run1.id, hostname=h) for h in hostnames]
    await findings_repo.persist_discovery_run(
        target_id=target.id, run_id=run1.id, items=items1, kinds={FindingKind.SUBDOMAIN}
    )
    await _succeed_run(db_session, tenant_id=tenant_a.id, run=run1)

    all_findings, _ = await findings_repo.list(target_id=target.id)
    first_seen_after_first_run = {f.fingerprint: f.first_seen_at for f in all_findings}

    # Run 2 — same findings
    run2 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    items2 = [_item(target.id, run_id=run2.id, hostname=h) for h in hostnames]
    await findings_repo.persist_discovery_run(
        target_id=target.id, run_id=run2.id, items=items2, kinds={FindingKind.SUBDOMAIN}
    )

    run_findings = await ScanRunFindingRepository(
        db_session, tenant_id=tenant_a.id
    ).list_for_run(run2.id)

    counts = _counts(run_findings)
    assert counts == {"unchanged": 2}, f"Expected all unchanged, got {counts}"

    # times_seen must have incremented to 2 for each
    all_findings, _ = await findings_repo.list(target_id=target.id)
    assert all(f.times_seen == 2 for f in all_findings), (
        "Each finding seen in two runs must have times_seen = 2"
    )

    assert {f.fingerprint: f.first_seen_at for f in all_findings} == (
        first_seen_after_first_run
    ), "first_seen_at must remain stable across runs"


# ---------------------------------------------------------------------------
# Test: a finding absent from run 2 → resolved (only that one, not others)
# ---------------------------------------------------------------------------


async def test_missing_finding_resolved_others_unchanged(db_session, two_tenants):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    target = await _make_target(
        db_session, tenant_id=tenant_a.id, name="resolve.example.com"
    )
    run1 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)

    findings_repo = FindingRepository(db_session, tenant_id=tenant_a.id)
    items1 = [
        _item(target.id, run_id=run1.id, hostname="stable.resolve.example.com"),
        _item(target.id, run_id=run1.id, hostname="gone.resolve.example.com"),
    ]
    await findings_repo.persist_discovery_run(
        target_id=target.id, run_id=run1.id, items=items1, kinds={FindingKind.SUBDOMAIN}
    )
    await _succeed_run(db_session, tenant_id=tenant_a.id, run=run1)

    # Run 2 — only the stable host
    run2 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    items2 = [_item(target.id, run_id=run2.id, hostname="stable.resolve.example.com")]
    await findings_repo.persist_discovery_run(
        target_id=target.id, run_id=run2.id, items=items2, kinds={FindingKind.SUBDOMAIN}
    )

    run_findings = await ScanRunFindingRepository(
        db_session, tenant_id=tenant_a.id
    ).list_for_run(run2.id)

    counts = _counts(run_findings)
    assert counts.get("resolved", 0) == 1, f"Expected 1 resolved, got {counts}"
    assert counts.get("unchanged", 0) == 1, f"Expected 1 unchanged, got {counts}"
    assert counts.get("new", 0) == 0


# ---------------------------------------------------------------------------
# Test: reappeared finding keeps original first_seen_at
# ---------------------------------------------------------------------------


async def test_reappeared_finding_keeps_original_first_seen_at(db_session, two_tenants):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    target = await _make_target(
        db_session, tenant_id=tenant_a.id, name="reappear.example.com"
    )
    run1 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)

    findings_repo = FindingRepository(db_session, tenant_id=tenant_a.id)
    hostname = "ghost.reappear.example.com"

    # Run 1 — finding appears
    await findings_repo.persist_discovery_run(
        target_id=target.id,
        run_id=run1.id,
        items=[_item(target.id, run_id=run1.id, hostname=hostname)],
        kinds={FindingKind.SUBDOMAIN},
    )
    await _succeed_run(db_session, tenant_id=tenant_a.id, run=run1)

    # Capture original first_seen_at
    findings_after_run1, _ = await findings_repo.list(target_id=target.id)
    original_first_seen = findings_after_run1[0].first_seen_at

    # Run 2 — finding absent → resolved
    run2 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    await findings_repo.persist_discovery_run(
        target_id=target.id, run_id=run2.id, items=[], kinds={FindingKind.SUBDOMAIN}
    )
    await _succeed_run(db_session, tenant_id=tenant_a.id, run=run2)

    # Run 3 — finding reappears
    run3 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    await findings_repo.persist_discovery_run(
        target_id=target.id,
        run_id=run3.id,
        items=[_item(target.id, run_id=run3.id, hostname=hostname)],
        kinds={FindingKind.SUBDOMAIN},
    )

    run3_findings = await ScanRunFindingRepository(
        db_session, tenant_id=tenant_a.id
    ).list_for_run(run3.id)
    counts = _counts(run3_findings)
    assert counts.get("reappeared", 0) == 1, f"Expected reappeared, got {counts}"

    # first_seen_at must not have changed
    findings_after_run3, _ = await findings_repo.list(target_id=target.id)
    assert findings_after_run3[0].first_seen_at == original_first_seen, (
        "first_seen_at must remain the original timestamp even after a reappearance"
    )


# ---------------------------------------------------------------------------
# Test: port scan does NOT resolve subdomain findings (cross-kind bug)
# ---------------------------------------------------------------------------


async def test_port_scan_does_not_resolve_subdomain_findings(db_session, two_tenants):
    """A run that scans only open_port findings must not resolve subdomain findings.

    This is the bug ADR-0004 §2 describes: resolve_missing_discoveries without
    kind-scoping would resolve *every* active finding not seen in the current run,
    including findings of completely different kinds.
    """
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    target = await _make_target(
        db_session, tenant_id=tenant_a.id, name="cross-kind.example.com"
    )
    findings_repo = FindingRepository(db_session, tenant_id=tenant_a.id)

    # Run 1: subdomain scan → creates a subdomain finding
    run1 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    await findings_repo.persist_discovery_run(
        target_id=target.id,
        run_id=run1.id,
        items=[_item(target.id, run_id=run1.id, hostname="sub.cross-kind.example.com")],
        kinds={FindingKind.SUBDOMAIN},
    )
    await _succeed_run(db_session, tenant_id=tenant_a.id, run=run1)

    # Run 2: port scan (a different kind, no subdomain items)
    # Without kind-scoping, this run would resolve the subdomain finding above.
    run2 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    port_item = {
        "target_id": target.id,
        "run_id": run2.id,
        "kind": FindingKind.OPEN_PORT,
        "value": "sub.cross-kind.example.com:80/tcp",
        "severity": "info",
    }
    await findings_repo.persist_discovery_run(
        target_id=target.id,
        run_id=run2.id,
        items=[port_item],
        kinds={FindingKind.OPEN_PORT},  # ← only this kind is in scope
    )

    # The subdomain finding must still be active
    all_findings, _ = await findings_repo.list(target_id=target.id)
    subdomain_findings = [f for f in all_findings if f.kind == FindingKind.SUBDOMAIN]
    assert len(subdomain_findings) == 1
    assert subdomain_findings[0].status == "active", (
        "A port scan must not resolve subdomain findings — "
        "resolve_missing_discoveries must be kind-scoped"
    )

    run2_findings = await ScanRunFindingRepository(
        db_session, tenant_id=tenant_a.id
    ).list_for_run(run2.id)
    assert _counts(run2_findings) == {"new": 1}
    assert all(
        item.finding_snapshot["attributes"]["kind"] == FindingKind.OPEN_PORT
        for item in run2_findings
    )


# ---------------------------------------------------------------------------
# Test: failed previous run is skipped; diff is against last successful run
# ---------------------------------------------------------------------------


async def test_diff_skips_failed_runs_uses_last_successful(db_session, two_tenants):
    tenant_a, _ = two_tenants
    principal = _owner(tenant_a.id)
    set_current_principal(principal)

    target = await _make_target(
        db_session, tenant_id=tenant_a.id, name="failskip.example.com"
    )
    findings_repo = FindingRepository(db_session, tenant_id=tenant_a.id)
    run_repo = ScanRunRepository(db_session, tenant_id=tenant_a.id)

    # Run 1 — succeeds, creates finding
    run1 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    await findings_repo.persist_discovery_run(
        target_id=target.id,
        run_id=run1.id,
        items=[_item(target.id, run_id=run1.id, hostname="ok.failskip.example.com")],
        kinds={FindingKind.SUBDOMAIN},
    )
    await _succeed_run(db_session, tenant_id=tenant_a.id, run=run1)

    # Run 2 — fails (simulated: create + immediately fail without producing findings)
    run2 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    run2_claimed = await run_repo.claim_for_job(run2.id, job_id=str(uuid.uuid4()))
    await run_repo.fail(
        run2_claimed.id,
        error_kind="terminal",
        error_message="worker crashed",
        attempt=1,
    )

    # Run 3 — succeeds again with the same finding
    run3 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    await findings_repo.persist_discovery_run(
        target_id=target.id,
        run_id=run3.id,
        items=[_item(target.id, run_id=run3.id, hostname="ok.failskip.example.com")],
        kinds={FindingKind.SUBDOMAIN},
    )

    run3_findings = await ScanRunFindingRepository(
        db_session, tenant_id=tenant_a.id
    ).list_for_run(run3.id)

    counts = _counts(run3_findings)
    # Should be unchanged (was active in run1, same details in run3).
    # If run2 were used as the baseline, it has no snapshots → the finding would
    # incorrectly appear as "new" or "reappeared".
    assert counts.get("unchanged", 0) == 1, (
        f"Expected unchanged (run2 was failed and should be skipped), got {counts}"
    )
    assert counts.get("new", 0) == 0, (
        "Finding must not be classified as new — it was active before the failed run"
    )


# ---------------------------------------------------------------------------
# Test: two tenants with identical findings diff independently
# ---------------------------------------------------------------------------


async def test_two_tenants_diff_independently(db_session, two_tenants):
    tenant_a, tenant_b = two_tenants
    # Both tenants scan the same hostname, so fingerprints will differ only by target_id
    hostname = "shared.example.com"

    for tenant_id in (tenant_a.id, tenant_b.id):
        principal = _owner(tenant_id)
        set_current_principal(principal)

        target = await _make_target(db_session, tenant_id=tenant_id, name=hostname)
        findings_repo = FindingRepository(db_session, tenant_id=tenant_id)

        run1 = await _make_run(db_session, tenant_id=tenant_id, target_id=target.id)
        await findings_repo.persist_discovery_run(
            target_id=target.id,
            run_id=run1.id,
            items=[_item(target.id, run_id=run1.id, hostname=f"sub.{hostname}")],
            kinds={FindingKind.SUBDOMAIN},
        )
        await _succeed_run(db_session, tenant_id=tenant_id, run=run1)

    # Now run a second scan for tenant_a only — tenant_b's findings must be unaffected
    principal_a = _owner(tenant_a.id)
    set_current_principal(principal_a)

    target_a = (await TargetRepository(db_session, tenant_id=tenant_a.id).list())[0][0]
    findings_repo_a = FindingRepository(db_session, tenant_id=tenant_a.id)
    run2_a = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target_a.id)
    await findings_repo_a.persist_discovery_run(
        target_id=target_a.id,
        run_id=run2_a.id,
        items=[],  # nothing seen → tenant_a's finding should become resolved
        kinds={FindingKind.SUBDOMAIN},
    )

    # Tenant A's finding is resolved
    findings_a, _ = await findings_repo_a.list(target_id=target_a.id)
    assert all(f.status == "resolved" for f in findings_a), (
        "Tenant A's findings should be resolved"
    )

    # Tenant B's finding is still active
    principal_b = _owner(tenant_b.id)
    set_current_principal(principal_b)
    findings_repo_b = FindingRepository(db_session, tenant_id=tenant_b.id)
    target_b = (await TargetRepository(db_session, tenant_id=tenant_b.id).list())[0][0]
    findings_b, _ = await findings_repo_b.list(target_id=target_b.id)
    assert all(f.status == "active" for f in findings_b), (
        "Tenant B's findings must not be affected by tenant A's diff"
    )


async def test_details_change_is_mutated(db_session, two_tenants):
    tenant_a, _ = two_tenants
    set_current_principal(_owner(tenant_a.id))

    target = await _make_target(
        db_session, tenant_id=tenant_a.id, name="mutated.example.com"
    )
    findings_repo = FindingRepository(db_session, tenant_id=tenant_a.id)
    hostname = "app.mutated.example.com"

    run1 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    await findings_repo.persist_discovery_run(
        target_id=target.id,
        run_id=run1.id,
        items=[
            _item(
                target.id,
                run_id=run1.id,
                hostname=hostname,
                details={"server": "nginx/1.25.4"},
            )
        ],
        kinds={FindingKind.SUBDOMAIN},
    )
    await _succeed_run(db_session, tenant_id=tenant_a.id, run=run1)

    run2 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    await findings_repo.persist_discovery_run(
        target_id=target.id,
        run_id=run2.id,
        items=[
            _item(
                target.id,
                run_id=run2.id,
                hostname=hostname,
                details={"server": "nginx/1.27.0"},
            )
        ],
        kinds={FindingKind.SUBDOMAIN},
    )

    run2_findings = await ScanRunFindingRepository(
        db_session, tenant_id=tenant_a.id
    ).list_for_run(run2.id)
    assert _counts(run2_findings) == {"mutated": 1}
    assert run2_findings[0].finding_snapshot["attributes"]["details"] == {
        "server": "nginx/1.27.0"
    }


async def test_degraded_run_does_not_resolve_missing_findings(db_session, two_tenants):
    tenant_a, _ = two_tenants
    set_current_principal(_owner(tenant_a.id))

    target = await _make_target(
        db_session, tenant_id=tenant_a.id, name="degraded.example.com"
    )
    findings_repo = FindingRepository(db_session, tenant_id=tenant_a.id)

    run1 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    await findings_repo.persist_discovery_run(
        target_id=target.id,
        run_id=run1.id,
        items=[
            _item(target.id, run_id=run1.id, hostname="a.degraded.example.com"),
            _item(target.id, run_id=run1.id, hostname="b.degraded.example.com"),
        ],
        kinds={FindingKind.SUBDOMAIN},
    )
    await _succeed_run(db_session, tenant_id=tenant_a.id, run=run1)

    run2 = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    await findings_repo.persist_discovery_run(
        target_id=target.id,
        run_id=run2.id,
        items=[_item(target.id, run_id=run2.id, hostname="a.degraded.example.com")],
        kinds={FindingKind.SUBDOMAIN},
        degraded=True,
    )

    findings, _ = await findings_repo.list(target_id=target.id)
    assert {f.value: f.status for f in findings} == {
        "a.degraded.example.com": "active",
        "b.degraded.example.com": "active",
    }
    run2_findings = await ScanRunFindingRepository(
        db_session, tenant_id=tenant_a.id
    ).list_for_run(run2.id)
    assert _counts(run2_findings) == {"unchanged": 2}


async def test_persist_discovery_run_replaces_snapshots_for_the_same_run(
    db_session, two_tenants
):
    tenant_a, _ = two_tenants
    set_current_principal(_owner(tenant_a.id))

    target = await _make_target(
        db_session, tenant_id=tenant_a.id, name="retry.example.com"
    )
    findings_repo = FindingRepository(db_session, tenant_id=tenant_a.id)
    run = await _make_run(db_session, tenant_id=tenant_a.id, target_id=target.id)
    items = [_item(target.id, run_id=run.id, hostname="a.retry.example.com")]

    await findings_repo.persist_discovery_run(
        target_id=target.id, run_id=run.id, items=items, kinds={FindingKind.SUBDOMAIN}
    )
    await findings_repo.persist_discovery_run(
        target_id=target.id, run_id=run.id, items=items, kinds={FindingKind.SUBDOMAIN}
    )

    snapshots = await ScanRunFindingRepository(
        db_session, tenant_id=tenant_a.id
    ).list_for_run(run.id)
    assert len(snapshots) == 1
    assert snapshots[0].classification == "unchanged"
