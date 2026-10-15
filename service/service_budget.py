"""Per-day / per-month spend caps for the LIVE gateway.

Separate from the eval ledger (`budget.py`): the harness tracks one cumulative
total for a research run; the service tracks rolling day/month spend against caps.

Design decision 1: when a cap is hit the gateway degrades to Layer-1-only (see
gateway.py), it does NOT block all traffic. That keeps budget exhaustion from
being turned into a denial of service (an attacker can't take the gateway fully
offline by burning the budget).
"""
import datetime
import json
import os
from pathlib import Path

STATE = Path(os.environ.get("AISPM_BUDGET_STATE",
                            str(Path(__file__).resolve().parent / "budget_state.json")))
DAILY_CAP = float(os.environ.get("AISPM_DAILY_CAP_USD", "1.00"))
MONTHLY_CAP = float(os.environ.get("AISPM_MONTHLY_CAP_USD", "20.00"))


def _today():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def _month():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")


def _load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def status():
    s = _load()
    day = s.get("day", {}).get(_today(), 0.0)
    mon = s.get("month", {}).get(_month(), 0.0)
    return {
        "day_spent": round(day, 6), "day_cap": DAILY_CAP,
        "month_spent": round(mon, 6), "month_cap": MONTHLY_CAP,
        "exhausted": day >= DAILY_CAP or mon >= MONTHLY_CAP,
    }


def can_spend():
    return not status()["exhausted"]


def record(cost):
    """Add an actual request cost to today's and this month's totals."""
    if not cost:
        return
    s = _load()
    d, m = _today(), _month()
    s.setdefault("day", {})[d] = round(s.get("day", {}).get(d, 0.0) + cost, 6)
    s.setdefault("month", {})[m] = round(s.get("month", {}).get(m, 0.0) + cost, 6)
    _save(s)
