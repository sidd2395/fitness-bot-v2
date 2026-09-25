"""Model prices, USD per million tokens. Fill in from Anthropic's pricing page.

Keys must match the model id passed to the API (MODEL_ONBOARDING, MODEL_COACH).
A model that is missing, or has a price left as None, still has its tokens
counted, but gets no cost; the test summary says which prices are missing.

cache_write is the 5-minute cache write price (the system prompt uses the
default ephemeral cache).
"""
from typing import Optional

PRICES: dict[str, dict[str, Optional[float]]] = {
    "claude-haiku-4-5-20251001": {
        "input": None,
        "output": None,
        "cache_read": None,
        "cache_write": None,
    },
    "claude-sonnet-5": {
        "input": None,
        "output": None,
        "cache_read": None,
        "cache_write": None,
    },
}

# usage field -> price key
_FIELDS = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_read_input_tokens": "cache_read",
    "cache_creation_input_tokens": "cache_write",
}


def usage_counts(usage) -> dict[str, int]:
    """The four token counts from a response.usage object; missing counts are 0."""
    return {field: getattr(usage, field, None) or 0 for field in _FIELDS}


def cost_usd(model: str, counts: dict[str, int]) -> Optional[float]:
    """Cost of one call, or None if any needed price for this model isn't set."""
    prices = PRICES.get(model)
    if prices is None:
        return None
    total = 0.0
    for field, key in _FIELDS.items():
        tokens = counts.get(field, 0)
        if not tokens:
            continue
        if prices.get(key) is None:
            return None
        total += tokens * prices[key] / 1_000_000
    return total
