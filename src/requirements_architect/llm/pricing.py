"""Cost estimation from an operator-supplied price table.

No prices are baked in: vendor pricing changes and must not be guessed.
Unknown models yield `None` (cost unknown), never a fabricated number.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from requirements_architect.llm.types import Usage


class ModelPrice(BaseModel):
    """USD per one million tokens."""

    input_per_mtok: Decimal
    output_per_mtok: Decimal


PriceTable = dict[str, ModelPrice]


def estimate_cost(model: str, usage: Usage, table: PriceTable) -> Decimal | None:
    price = table.get(model)
    if price is None:
        return None
    million = Decimal(1_000_000)
    return (
        Decimal(usage.input_tokens) * price.input_per_mtok
        + Decimal(usage.output_tokens) * price.output_per_mtok
    ) / million
