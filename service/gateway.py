"""Live AI-SPM gateway core. The HTTP layer is in app.py.

Design decisions (CASE_STUDY.md §9, B1 audit, B monitoring verdict):

  1. Judge or budget unavailable -> DEGRADE to Layer-1-only (verdict=None), never
     block-all (no budget-exhaustion DoS). A judge error degrades the same way
     (layer="judge-error") instead of a silent benign allow. On a Haiku error,
     Sonnet is tried once (a "rescue", tracked separately from band escalation);
     if both fail -> judge-error.
  2. Per-request budget charged to rolling day/month caps (service_budget),
     separate from the eval ledger. Soft cap; a judge-path semaphore bounds the
     overshoot (~= concurrency x max per-request cost ~= $0.06).
  4. Scope guard: raw length is checked BEFORE normalization (cheap short-circuit);
     then NFKC-normalized length and base64-run are checked (full-width base64 folds
     to ASCII). Tool/document output is not accepted (indirect injection out of
     scope). Known gap: URL-safe base64 (-/_) is not decoded by Layer 1.
  5. No request-path cache (judge freshness; a cache key would index inputs that
     got through).

Monitoring is in-memory and resets on restart -- it produces "go look" signals,
not a diagnosis. The durable record is the structured log (one JSON line per
request, plus alert/degraded event lines). All monitor state is derived from one
deque of the last N judgments under a single lock.
"""
import collections
import datetime
import hashlib
import json
import os
import re
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config               # noqa: E402
import layer1               # noqa: E402
import layer2               # noqa: E402
import service_budget as sb  # noqa: E402

MAX_INPUT_CHARS = int(os.environ.get("AISPM_MAX_INPUT_CHARS", "8000"))
MAX_B64_RUN = int(os.environ.get("AISPM_MAX_B64_RUN", "2000"))
JUDGE_CONCURRENCY = int(os.environ.get("AISPM_JUDGE_CONCURRENCY", "8"))
WINDOW = int(os.environ.get("AISPM_MONITOR_WINDOW", "100"))
HASH_WINDOW = int(os.environ.get("AISPM_HASH_WINDOW", "1000"))
MIN_SAMPLES = 30
ESC_FIRE, ESC_CLEAR = 0.35, 0.25           # escalation-rate alert hysteresis
JERR_FIRE, JERR_CLEAR = 0.10, 0.05         # judge-error-rate alert hysteresis
RISK_RANK = config.RISK_RANK
CUT = RISK_RANK[config.RISK_CUTOFF]
HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"

_JUDGE_SEM = threading.Semaphore(JUDGE_CONCURRENCY)
_MLOCK = threading.Lock()
_B64 = re.compile(r"[A-Za-z0-9+/]{%d,}={0,2}" % MAX_B64_RUN)

METRICS = {"requests": 0, "block": 0, "allow": 0, "reject": 0, "judged": 0,
           "escalated": 0, "rescued": 0, "degraded": 0, "judge_error": 0}
_JUDGED = collections.deque(maxlen=WINDOW)       # one record per judged request
_HASH_WINDOW = collections.deque(maxlen=HASH_WINDOW)  # (client_id, input_hash), ALL requests
_last_degraded = False
_esc_alerting = False
_jerr_alerting = False


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _is_error(v):
    return v.get("risk") == "unknown" or str(v.get("reasoning", "")).startswith("[error]")


def _scope_violation(norm):
    """Normalized-text checks (raw length is handled before normalization)."""
    if len(norm) > MAX_INPUT_CHARS:
        return f"normalized input too long ({len(norm)} > {MAX_INPUT_CHARS} chars)"
    m = _B64.search(norm)
    if m:
        return f"oversized base64 blob ({len(m.group(0))} chars)"
    return None


def _cascade_live(norm):
    """Haiku first. Escalate to Sonnet on a low/medium band verdict (escalated) OR
    on a Haiku error (rescued). Returns
    (verdict, escalated, rescued, cost, error, haiku_ms, sonnet_ms).
    escalated = band escalation only; rescued = Haiku-error fallback; error = no
    usable verdict (both models failed)."""
    hv = layer2.judge_real(norm, model=HAIKU, record=False)
    h_ms = hv.get("_usage", {}).get("latency_ms")
    cost = hv.get("_usage", {}).get("cost_usd", 0.0)
    h_err = _is_error(hv)
    if not h_err and hv.get("risk") not in config.CASCADE_ESCALATE:
        return hv, False, False, cost, False, h_ms, None
    sv = layer2.judge_real(norm, model=SONNET, record=False)
    s_ms = sv.get("_usage", {}).get("latency_ms")
    cost += sv.get("_usage", {}).get("cost_usd", 0.0)
    escalated = not h_err        # band-triggered call
    rescued = h_err              # error-triggered call
    if not _is_error(sv):
        return sv, escalated, rescued, cost, False, h_ms, s_ms
    if not h_err:
        return hv, escalated, rescued, cost, False, h_ms, s_ms   # keep Haiku's verdict
    return sv, escalated, rescued, cost, True, h_ms, s_ms         # both failed


def _eval_alerts():
    """Called under _MLOCK. Returns a list of (event_name, rate, n) to log."""
    global _esc_alerting, _jerr_alerting
    evs = []
    n = len(_JUDGED)
    if n >= MIN_SAMPLES:
        esc = sum(r["escalated"] for r in _JUDGED) / n
        if esc > ESC_FIRE and not _esc_alerting:
            _esc_alerting = True
            evs.append(("escalation_alert", esc, n))
        elif esc < ESC_CLEAR and _esc_alerting:
            _esc_alerting = False
            evs.append(("escalation_alert_clear", esc, n))
        jerr = sum(r["error"] for r in _JUDGED) / n
        if jerr > JERR_FIRE and not _jerr_alerting:
            _jerr_alerting = True
            evs.append(("judge_error_alert", jerr, n))
        elif jerr < JERR_CLEAR and _jerr_alerting:
            _jerr_alerting = False
            evs.append(("judge_error_alert_clear", jerr, n))
    return evs


def _log_degraded_transition(exhausted):
    global _last_degraded
    ev = None
    with _MLOCK:
        if exhausted != _last_degraded:
            _last_degraded = exhausted
            ev = "degraded_enter" if exhausted else "degraded_exit"
    if ev:
        print(json.dumps({"ts": _now_iso(), "event": ev}), flush=True)


def _result(decision, verdict, layer, reason, client_id, ihash, degraded=False,
            risk=None, category=None, escalated=False, rescued=False, error=False,
            cost=0.0, haiku_ms=None, sonnet_ms=None, t0=None):
    events = []
    with _MLOCK:
        METRICS["requests"] += 1
        METRICS[decision] = METRICS.get(decision, 0) + 1
        if layer == "cascade":
            METRICS["judged"] += 1
        if layer == "judge-error":
            METRICS["judge_error"] += 1
        if escalated:
            METRICS["escalated"] += 1
        if rescued:
            METRICS["rescued"] += 1
        if degraded:
            METRICS["degraded"] += 1
        _HASH_WINDOW.append((client_id, ihash))           # ALL requests
        if layer in ("cascade", "judge-error"):
            _JUDGED.append({"client": client_id, "escalated": escalated,
                            "rescued": rescued, "error": error,
                            "final_risk": risk if risk else ("error" if error else "none")})
            events = _eval_alerts()
    rec = {
        "ts": _now_iso(), "client_id": client_id, "input_hash": ihash,
        "decision": decision, "verdict": verdict, "layer": layer,
        "reason": (reason or "")[:300], "degraded": degraded,
        "risk": risk, "category": category,
        "escalated": escalated, "rescued": rescued,
        "cost_usd": round(cost, 6), "haiku_ms": haiku_ms, "sonnet_ms": sonnet_ms,
        "latency_ms": round((time.time() - t0) * 1000, 1) if t0 else None,
    }
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    for name, rate, n in events:
        print(json.dumps({"ts": _now_iso(), "event": name,
                          "rate": round(rate, 3), "window": n}), flush=True)
    return rec


def check(text, client_id="anonymous"):
    """Classify one input. Returns (and logs) the structured decision record."""
    t0 = time.time()

    if len(text) > MAX_INPUT_CHARS:                    # C-3: raw check BEFORE normalize
        ih = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return _result("reject", None, "scope",
                       f"raw input too long ({len(text)} > {MAX_INPUT_CHARS} chars)",
                       client_id, ih, t0=t0)

    norm = layer1.normalize(text)                      # decision 4
    ihash = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]

    violation = _scope_violation(norm)
    if violation:
        return _result("reject", None, "scope", violation, client_id, ihash, t0=t0)

    matched, _ = layer1.static_scan(norm)
    if matched:
        return _result("block", "attack", "layer1",
                       ";".join(m[1] for m in matched), client_id, ihash, t0=t0)

    exhausted = not sb.can_spend()
    _log_degraded_transition(exhausted)
    if exhausted:
        return _result("allow", None, "layer1-degraded",
                       "budget exhausted; Layer 1 only (not judged)",
                       client_id, ihash, degraded=True, t0=t0)

    with _JUDGE_SEM:                                   # bound concurrency -> bound overshoot
        final, escalated, rescued, cost, err, h_ms, s_ms = _cascade_live(norm)
    sb.record(cost)

    if err:
        return _result("allow", None, "judge-error",
                       "judge failed (both models); Layer 1 only",
                       client_id, ihash, degraded=True, rescued=rescued, error=True,
                       cost=cost, haiku_ms=h_ms, sonnet_ms=s_ms, t0=t0)

    risk = final.get("risk", "none")
    attack = RISK_RANK.get(risk, 0) >= CUT             # "unknown" never reaches here
    return _result("block" if attack else "allow",
                   "attack" if attack else "benign",
                   "cascade", final.get("reasoning", ""), client_id, ihash,
                   risk=risk, category=final.get("category"),
                   escalated=escalated, rescued=rescued, cost=cost,
                   haiku_ms=h_ms, sonnet_ms=s_ms, t0=t0)


def health():
    st = sb.status()
    return {"status": "degraded" if st["exhausted"] else "ok", "budget": st}


def metrics():
    with _MLOCK:
        out = dict(METRICS)
        judged = list(_JUDGED)
        hashes = list(_HASH_WINDOW)
        esc_alerting, jerr_alerting = _esc_alerting, _jerr_alerting
    n = len(judged) or 1
    dist = collections.Counter(r["final_risk"] for r in judged if r["escalated"])
    pcr = collections.Counter(r["client"] for r in judged if r["escalated"])
    dup = round(1 - len(set(hashes)) / len(hashes), 3) if hashes else 0.0
    out["window_size"] = len(judged)
    out["escalation_rate"] = round(out["escalated"] / (out["judged"] or 1), 3)  # cumulative
    out["escalation_rate_window"] = round(sum(r["escalated"] for r in judged) / n, 3)
    out["escalation_alerting"] = esc_alerting
    out["escalated_verdict_dist"] = dict(dist)
    out["per_client_recent"] = [{"client_id": c, "escalated": k}
                                for c, k in pcr.most_common(20)]
    out["judge_error_rate_window"] = round(sum(r["error"] for r in judged) / n, 3)
    out["judge_error_alerting"] = jerr_alerting
    out["input_hash_dup_rate"] = dup
    out["budget"] = sb.status()
    return out
