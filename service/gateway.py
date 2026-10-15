"""Live AI-SPM gateway core. The HTTP layer is in app.py.

Design decisions (CASE_STUDY.md §9, B-phase handoff, B1 audit B1_AUDIT_VERDICT.md):

  1. Judge or budget unavailable -> DEGRADE to Layer-1-only (verdict=None), never
     block-all, so a budget attack can't become a denial of service. A judge error
     degrades the SAME way (layer="judge-error", logged + counted) instead of being
     silently recorded as a benign allow.
  2. Per-request budget: the actual cost is charged to rolling day/month caps
     (service_budget), separate from the eval ledger.
  3. Soft cap: checked once before the judge call. A judge-path semaphore bounds the
     overshoot to ~= concurrency x max per-request cost ~= $0.06.
  4. Scope guard runs AFTER NFKC normalization (full-width base64 folds to ASCII;
     homoglyphs can multiply length). Raw length is also capped (HTTP layer + here).
     Tool/document output is not accepted -- indirect injection is out of scope
     (CASE_STUDY §10). Known gap: URL-safe base64 (-/_) is not decoded by Layer 1.
  5. No request-path cache. Reasons: judge freshness (model/prompt changes apply at
     once), and a cache key would become a stored index of inputs that got through.
     (Probing is better handled by client rate limiting -- future work.)

Judge = the validated cascade: Haiku first, escalate low+medium to Sonnet (Sonnet
overrides). On a Haiku error, Sonnet is tried once; if both fail -> judge-error.
"""
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
RISK_RANK = config.RISK_RANK
CUT = RISK_RANK[config.RISK_CUTOFF]
HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"

_JUDGE_SEM = threading.Semaphore(JUDGE_CONCURRENCY)
_MLOCK = threading.Lock()
_B64 = re.compile(r"[A-Za-z0-9+/]{%d,}={0,2}" % MAX_B64_RUN)

METRICS = {"requests": 0, "block": 0, "allow": 0, "reject": 0,
           "judged": 0, "escalated": 0, "degraded": 0, "judge_error": 0}
_last_degraded = False


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _is_error(v):
    return v.get("risk") == "unknown" or str(v.get("reasoning", "")).startswith("[error]")


def _scope_violation(raw, norm):
    if len(raw) > MAX_INPUT_CHARS:
        return f"raw input too long ({len(raw)} > {MAX_INPUT_CHARS} chars)"
    if len(norm) > MAX_INPUT_CHARS:
        return f"normalized input too long ({len(norm)} > {MAX_INPUT_CHARS} chars)"
    m = _B64.search(norm)
    if m:
        return f"oversized base64 blob ({len(m.group(0))} chars)"
    return None


def _cascade_live(norm):
    """Haiku first; escalate low+medium (or, on a Haiku error, one Sonnet retry).
    Returns (verdict, escalated, cost, error, haiku_ms, sonnet_ms). error=True only
    when NO usable verdict exists (both models failed)."""
    hv = layer2.judge_real(norm, model=HAIKU, record=False)
    h_ms = hv.get("_usage", {}).get("latency_ms")
    cost = hv.get("_usage", {}).get("cost_usd", 0.0)
    h_err = _is_error(hv)
    if not (h_err or hv.get("risk") in config.CASCADE_ESCALATE):
        return hv, False, cost, False, h_ms, None
    sv = layer2.judge_real(norm, model=SONNET, record=False)
    s_ms = sv.get("_usage", {}).get("latency_ms")
    cost += sv.get("_usage", {}).get("cost_usd", 0.0)
    if not _is_error(sv):
        return sv, True, cost, False, h_ms, s_ms
    if not h_err:
        return hv, False, cost, False, h_ms, s_ms   # keep Haiku's usable verdict
    return sv, False, cost, True, h_ms, s_ms         # both failed -> no verdict


def _log_degraded_transition(exhausted):
    global _last_degraded
    if exhausted != _last_degraded:
        _last_degraded = exhausted
        print(json.dumps({"ts": _now_iso(),
                          "event": "degraded_enter" if exhausted else "degraded_exit"}),
              flush=True)


def _result(decision, verdict, layer, reason, client_id, ihash, degraded=False,
            risk=None, category=None, escalated=False, cost=0.0,
            haiku_ms=None, sonnet_ms=None, t0=None):
    with _MLOCK:
        METRICS["requests"] += 1
        METRICS[decision] = METRICS.get(decision, 0) + 1
        if layer == "cascade":
            METRICS["judged"] += 1
        if layer == "judge-error":
            METRICS["judge_error"] += 1
        if escalated:
            METRICS["escalated"] += 1
        if degraded:
            METRICS["degraded"] += 1
    rec = {
        "ts": _now_iso(), "client_id": client_id, "input_hash": ihash,
        "decision": decision, "verdict": verdict, "layer": layer,
        "reason": (reason or "")[:300], "degraded": degraded,
        "risk": risk, "category": category, "escalated": escalated,
        "cost_usd": round(cost, 6), "haiku_ms": haiku_ms, "sonnet_ms": sonnet_ms,
        "latency_ms": round((time.time() - t0) * 1000, 1) if t0 else None,
    }
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    return rec


def check(text, client_id="anonymous"):
    """Classify one input. Returns (and logs) the structured decision record."""
    t0 = time.time()
    norm = layer1.normalize(text)                 # decision 4: normalize FIRST
    ihash = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]

    violation = _scope_violation(text, norm)
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

    with _JUDGE_SEM:                               # bound concurrency -> bound overshoot
        final, escalated, cost, err, h_ms, s_ms = _cascade_live(norm)
    sb.record(cost)

    if err:                                        # decision 1: judge error -> degrade
        return _result("allow", None, "judge-error",
                       "judge failed (both models); Layer 1 only",
                       client_id, ihash, degraded=True, cost=cost,
                       haiku_ms=h_ms, sonnet_ms=s_ms, t0=t0)

    risk = final.get("risk", "none")
    attack = RISK_RANK.get(risk, 0) >= CUT         # "unknown" never reaches here
    return _result("block" if attack else "allow",
                   "attack" if attack else "benign",
                   "cascade", final.get("reasoning", ""), client_id, ihash,
                   risk=risk, category=final.get("category"),
                   escalated=escalated, cost=cost, haiku_ms=h_ms, sonnet_ms=s_ms, t0=t0)


def health():
    st = sb.status()
    return {"status": "degraded" if st["exhausted"] else "ok", "budget": st}


def metrics():
    with _MLOCK:
        out = dict(METRICS)
    judged = out["judged"] or 1
    out["escalation_rate"] = round(out["escalated"] / judged, 3)
    out["budget"] = sb.status()
    return out
