"""Per-day / per-month spend caps for the LIVE gateway (separate from the eval ledger).

Design decision 1: on exhaustion the gateway degrades to Layer-1-only, never
block-all (no budget-exhaustion DoS).

The cap is SOFT: it is checked once before the judge call, so spend can overshoot.
The overshoot is bounded by the gateway's judge-concurrency semaphore
(ceiling = concurrency x max per-request cost ~= 8 x $0.007 ~= $0.06). A
threading.Lock makes the ledger read-modify-write atomic, so concurrent requests
can't lose updates (B1 audit 1-3 / §4).
"""
import datetime
import json
import os
import threading
from pathlib import Path

STATE = Path(os.environ.get(
    "AISPM_BUDGET_STATE",
    str(Path(__file__).resolve().parent / "budget_state.json")))
DAILY_CAP = float(os.environ.get("AISPM_DAILY_CAP_USD", "1.00"))
MONTHLY_CAP = float(os.environ.get("AISPM_MONTHLY_CAP_USD", "20.00"))
KEEP_DAYS = 60
KEEP_MONTHS = 13

_LOCK = threading.Lock()


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _today():
    return _now().strftime("%Y-%m-%d")


def _month():
    return _now().strftime("%Y-%m")


def _load():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _prune(state):
    cut_day = (_now() - datetime.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    cut_mon = (_now() - datetime.timedelta(days=31 * KEEP_MONTHS)).strftime("%Y-%m")
    state["day"] = {k: v for k, v in state.get("day", {}).items() if k >= cut_day}
    state["month"] = {k: v for k, v in state.get("month", {}).items() if k >= cut_mon}
    return state


def status():
    with _LOCK:
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
    """Atomically add one request's cost to today's and this month's totals."""
    if not cost:
        return
    with _LOCK:
        s = _load()
        d, m = _today(), _month()
        s.setdefault("day", {})[d] = round(s.get("day", {}).get(d, 0.0) + cost, 6)
        s.setdefault("month", {})[m] = round(s.get("month", {}).get(m, 0.0) + cost, 6)
        _prune(s)
        _save(s)
