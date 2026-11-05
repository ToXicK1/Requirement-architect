"""Stage outputs complete enough that the audit finds nothing it can auto-fix. Test-only."""

from __future__ import annotations

from typing import Any

from tests.conftest import MINIMAL_QA, MINIMAL_SECURITY
from tests.doc_helpers import FULL_DEPLOY

_AREAS = ["authentication", "authorization", "input_validation", "secrets", "encryption", "audit"]
_STRIDE = [
    "spoofing",
    "tampering",
    "repudiation",
    "information_disclosure",
    "denial_of_service",
    "elevation_of_privilege",
]

SECURITY_OK: dict[str, Any] = MINIMAL_SECURITY | {
    "controls": [
        {
            "key": f"SC{n}",
            "name": f"Control {a}",
            "description": "d",
            "area": a,
            "requirement_ids": ["FR-001"],
        }
        for n, a in enumerate(_AREAS, 1)
    ],
    "threats": [
        {
            "key": f"TH{n}",
            "title": f"Threat {c}",
            "category": c,
            "asset": "accounts",
            "description": "d",
            "likelihood": "low",
            "impact": "low",
            "control_keys": [f"SC{n}"],
        }
        for n, c in enumerate(_STRIDE, 1)
    ],
    "test_plan": [
        {"name": f"Test {n}", "method": "m", "control_keys": [f"SC{n}"]} for n in range(1, 7)
    ],
}

QA_OK: dict[str, Any] = MINIMAL_QA | {
    "strategy": [
        {"test_type": t, "approach": "a"} for t in ("unit", "integration", "security", "api")
    ],
    "test_cases": [MINIMAL_QA["test_cases"][0] | {"requirement_ids": ["FR-001"]}],
    "deployment": FULL_DEPLOY,
}
