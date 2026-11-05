import pytest

from requirements_architect.research.evidence import (
    classify_source,
    normalize,
    verify_findings,
)
from requirements_architect.schemas.research import (
    FindingKind,
    RawFinding,
    Reliability,
    SourceType,
    VerificationStatus,
)

TEXTS = {
    "S-001": "FastAPI is a modern, fast web framework for building APIs with Python 3.8+ based on standard type hints.",
    "S-002": "Pydantic   validates\n data using Python type annotations.",
}
V, U, X = VerificationStatus.VERIFIED, VerificationStatus.UNVERIFIED, VerificationStatus.UNSUPPORTED


def fact(claim="c", sources=("S-001",), quote=None):
    return RawFinding(kind=FindingKind.FACT, claim=claim, source_ids=list(sources), quote=quote)


def test_fact_with_verbatim_quote_is_verified():
    (f,) = verify_findings([fact(quote="a modern, fast web framework for building APIs")], TEXTS)
    assert f.verification is V and f.finding_id == "F-001" and "S-001" in f.verification_note


def test_matching_ignores_case_whitespace_and_curly_quotes():
    (f,) = verify_findings(
        [fact(sources=["S-002"], quote="PYDANTIC validates DATA using\npython type annotations")],
        TEXTS,
    )
    assert f.verification is V
    assert normalize("It\u2019s \u201cfine\u201d") == 'it\'s "fine"'


def test_fabricated_quote_is_not_verified():
    (f,) = verify_findings(
        [fact(quote="FastAPI natively supports GraphQL subscriptions out of the box")], TEXTS
    )
    assert f.verification is U and "not found" in f.verification_note


def test_quote_must_be_in_a_CITED_source_not_just_any_source():
    (f,) = verify_findings(
        [fact(sources=["S-001"], quote="validates data using Python type annotations")], TEXTS
    )
    assert f.verification is U  # exists in S-002, but S-001 was cited


def test_fact_without_source_is_unsupported():
    (f,) = verify_findings([fact(sources=[], quote="a modern, fast web framework")], TEXTS)
    assert f.verification is X


def test_unknown_source_ids_are_dropped_and_noted_never_trusted():
    (f,) = verify_findings([fact(sources=["S-999"], quote="a modern, fast web framework")], TEXTS)
    assert f.verification is X and f.source_ids == [] and "S-999" in f.verification_note


def test_partially_unknown_sources_keeps_known_ones():
    (f,) = verify_findings(
        [fact(sources=["S-999", "S-001"], quote="modern, fast web framework")], TEXTS
    )
    assert f.verification is V and f.source_ids == ["S-001"] and "ignored" in f.verification_note


@pytest.mark.parametrize(
    "quote", [None, "", "   ", "FastAPI", "web framework", "modern, fast web framework"[:24]]
)
def test_missing_or_trivially_short_quote_cannot_verify(quote):
    (f,) = verify_findings([fact(quote=quote)], TEXTS)
    assert f.verification is U


@pytest.mark.parametrize("kind", [FindingKind.RECOMMENDATION, FindingKind.ASSUMPTION])
def test_recommendations_and_assumptions_are_never_verified_even_with_perfect_quote(kind):
    raw = RawFinding(
        kind=kind,
        claim="use it",
        source_ids=["S-001"],
        quote="a modern, fast web framework for building APIs",
    )
    (f,) = verify_findings([raw], TEXTS)
    assert f.verification is U and kind.value in f.verification_note


def test_ids_are_sequential_and_stable_in_order():
    fs = verify_findings([fact(claim="a"), fact(claim="b"), fact(claim="c")], TEXTS)
    assert [f.finding_id for f in fs] == ["F-001", "F-002", "F-003"]


def test_model_cannot_smuggle_verification_fields():
    f = RawFinding.model_validate(
        {
            "kind": "fact",
            "claim": "x",
            "source_ids": [],
            "verification": "verified",
            "finding_id": "F-1",
        }
    )
    assert not hasattr(f, "verification")
    (out,) = verify_findings([f], TEXTS)
    assert out.verification is X


@pytest.mark.parametrize(
    ("url", "stype", "rel"),
    [
        (
            "https://docs.python.org/3/library/asyncio.html",
            SourceType.OFFICIAL_DOCS,
            Reliability.HIGH,
        ),
        ("https://pypi.org/pypi/fastapi/json", SourceType.PACKAGE_REGISTRY, Reliability.HIGH),
        ("https://owasp.org/www-project-top-ten/", SourceType.STANDARD, Reliability.HIGH),
        ("https://github.com/tiangolo/fastapi", SourceType.REPOSITORY, Reliability.MEDIUM),
        ("https://random-blog.example.com/post", SourceType.WEB, Reliability.LOW),
    ],
)
def test_source_classification(url, stype, rel):
    t, r, basis = classify_source(url)
    assert (t, r) == (stype, rel) and basis


@pytest.mark.parametrize(
    "url",
    [
        "https://docs.python.org.evil.com/x",
        "https://evildocs.python.org.attacker.io/",
        "https://notpypi.org/x",
        "https://evilgithub.com/x",
    ],
)
def test_lookalike_hosts_do_not_inherit_trust(url):
    t, r, _ = classify_source(url)
    assert (t, r) == (SourceType.WEB, Reliability.LOW)


def test_quote_length_boundary():
    ok = "a modern, fast web frame"  # 24 chars -> too short
    assert len(ok) == 24
    assert verify_findings([fact(quote=ok)], TEXTS)[0].verification is U
    ok25 = "a modern, fast web framew"
    assert len(ok25) == 25
    assert verify_findings([fact(quote=ok25)], TEXTS)[0].verification is V
