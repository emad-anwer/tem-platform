from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.core.fingerprint import FindingKind, compute_fingerprint


def test_fingerprint_is_stable_across_processes() -> None:
    source_root = str(Path(__file__).resolve().parents[2] / "src")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (source_root, env.get("PYTHONPATH", "")) if part
    )
    script = (
        "from app.core.fingerprint import FindingKind, compute_fingerprint; "
        "print(compute_fingerprint(FindingKind.SUBDOMAIN, "
        "'6b1a5e3a-7b5e-4f4e-aef6-2f73b13d5a1e', 'www.example.com'))"
    )

    fingerprints = [
        subprocess.check_output([sys.executable, "-c", script], env=env, text=True)
        for _ in range(2)
    ]

    assert fingerprints[0] == fingerprints[1]
    assert fingerprints[0].strip() == compute_fingerprint(
        FindingKind.SUBDOMAIN,
        "6b1a5e3a-7b5e-4f4e-aef6-2f73b13d5a1e",
        "www.example.com",
    )


def test_finding_kind_is_part_of_fingerprint() -> None:
    target_id = "6b1a5e3a-7b5e-4f4e-aef6-2f73b13d5a1e"

    assert compute_fingerprint(FindingKind.SUBDOMAIN, target_id, "80") != (
        compute_fingerprint(FindingKind.OPEN_PORT, target_id, "80")
    )
