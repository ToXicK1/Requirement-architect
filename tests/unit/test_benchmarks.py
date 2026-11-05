import json
from pathlib import Path

from requirements_architect.api.schemas import NewProject

DATA = json.loads(
    (Path(__file__).resolve().parents[2] / "benchmarks" / "problems.json").read_text("utf-8")
)


def test_at_least_twenty_unique_valid_problems():
    assert len(DATA) >= 20
    assert len({p["id"] for p in DATA}) == len(DATA)
    for p in DATA:
        NewProject(name=p["id"], problem_statement=p["problem_statement"])  # same limits as the API


def test_covers_hard_categories():
    cats = {p["category"] for p in DATA}
    assert {
        "vague",
        "contradictory",
        "adversarial",
        "out-of-scope",
        "multilingual",
        "regulated",
        "ai",
    } <= cats
