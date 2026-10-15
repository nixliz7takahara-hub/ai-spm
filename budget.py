"""Persistent cumulative-cost ledger + hard cap (plan requirement #2).

Spend is persisted to a JSON file so the cap is enforced ACROSS runs, not just
within one process. check_before_call() is the guard; call it before every real
API request.
"""
import json

import config
from config import BUDGET_CAP_USD, BUDGET_FILE


class BudgetExceeded(Exception):
    """Raised when a real API call would push spend over the hard cap."""


def _load():
    try:
        return json.loads(BUDGET_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"spent_usd": 0.0, "calls": 0}


def _save(state):
    BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    BUDGET_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def cost_of(input_tokens, output_tokens, model=None):
    pin, pout = config.pricing_for(model or config.MODEL)
    return (input_tokens / 1_000_000) * pin + (output_tokens / 1_000_000) * pout


def current_spend():
    return _load()["spent_usd"]


def check_before_call():
    """Raise BudgetExceeded if we are already at/over the cap."""
    spent = current_spend()
    if spent >= BUDGET_CAP_USD:
        raise BudgetExceeded(
            f"cumulative ${spent:.4f} >= cap ${BUDGET_CAP_USD:.2f}; refusing API call"
        )
    return spent


def record(input_tokens, output_tokens, model=None):
    """Add the cost of one call to the persistent ledger; return new total."""
    state = _load()
    state["spent_usd"] = round(
        state["spent_usd"] + cost_of(input_tokens, output_tokens, model), 6
    )
    state["calls"] = state.get("calls", 0) + 1
    _save(state)
    return state["spent_usd"]
