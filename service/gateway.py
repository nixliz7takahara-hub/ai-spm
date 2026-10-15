"""Live AI-SPM gateway core. The HTTP layer is in app.py.

Implements the design decisions from the case study (CASE_STUDY.md §9) and the
B-phase handoff:

  1. Budget exhaustion -> DEGRADE to Layer-1-only, never block-all. Keeps a budget
     attack from becoming a denial of service.
  2. Per-request budget: no up-front estimate; account the ACTUAL cost of each
     request against rolling day/month caps (service_budget).
  4. Scope guard: reject oversized input and oversized base64 blobs up front. Tool
     / document output is NOT accepted here -- indirect (RAG) injection is out of
     scope (CASE_STUDY.md §10), and a gateway that ingests tool output would need
     its own threat model.
  5. Cache: the request path does NOT reuse the eval verdict cache. Re-judging the
     same input each time avoids handing an attacker a stable probing oracle. (A
     short-TTL cache is a future option; default is no cache.)

The judge runs as the validated cascade: Haiku first, escalate the low+medium band
to Sonnet (config.CASCADE_ESCALATE), Sonnet overrides.
"""
import datetime
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config        # noqa: E402
import layer1        # noqa: E402
import layer2        # noqa: E402
import service_budget as sb   # noqa: E402

MAX_INPUT_CHARS = int(os.environ.get("AISPM_MAX_INPUT_CHARS", "8000"))
MAX_B64_RUN = int(os.environ.get("AISPM_MAX_B64_RUN", "2000"))
RISK_RANK = config.RISK_RANK
CUT = RISK_RANK[config.RISK_CUTOFF]
HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"

METRICS = {"requests": 0, "block": 0, "allow": 0, "reject": 0,
           "judged": 0, "escalated": 0, "degraded": 0, "errors": 0}


def _scope_violation(text):
    if len(text) > MAX_INPUT_CHARS:
        return f"input too long ({len(text)} > {MAX_INPUT_CHARS} chars)"
    m = re.search(r"[A-Za-z0-9+/]{%d,}={0,2}" % MAX_B64_RUN, text)
    if m:
        return f"oversized base64 blob ({len(m.group(0))} chars)"
    return None


def _cascade_live(norm):
    """Haiku first; escalate the configured band to Sonnet. No eval cache; cost
    is accounted by the caller from the returned total."""
    hv = layer2.judge_real(norm, model=HAIKU, record=False)
    cost = hv.get("_usage", {}).get("cost_usd", 0.0)
    final, escalated, err = hv, False, str(hv.get("reasoning", "")).startswith("[error]")
    if hv.get("risk") in config.CASCADE_ESCALATE:
        sv = layer2.judge_real(norm, model=SONNET, record=False)
        cost += sv.get("_usage", {}).get("cost_usd", 0.0)
        if not str(sv.get("reasoning", "")).startswith("[error]"):
            final, escalated = sv, True
        else:
            err = True
    return final, escalated, cost, err


def _result(decision, verdict, layer, reason, degraded=False, risk=None,
            category=None, escalated=False, error=False, cost=0.0, t0=None):
    METRICS["requests"] += 1
    METRICS[decision] = METRICS.get(decision, 0) + 1
    if layer == "cascade":
        METRICS["judged"] += 1
    if escalated:
        METRICS["escalated"] += 1
    if degraded:
        METRICS["degraded"] += 1
    if error:
        METRICS["errors"] += 1
    rec = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "decision": decision,          # block | allow | reject
        "verdict": verdict,            # attack | benign | None
        "layer": layer,                # scope | layer1 | cascade | layer1-degraded
        "reason": (reason or "")[:300],
        "degraded": degraded,
        "risk": risk, "category": category, "escalated": escalated,
        "error": error, "cost_usd": round(cost, 6),
        "latency_ms": round((time.time() - t0) * 1000, 1) if t0 else None,
    }
    print(json.dumps(rec, ensure_ascii=False), flush=True)   # structured log line
    return rec


def check(text):
    """Classify one input. Returns the structured decision record (also logged)."""
    t0 = time.time()

    violation = _scope_violation(text)
    if violation:
        return _result("reject", None, "scope", violation, t0=t0)

    l1 = layer1.inspect(text)
    if l1["blocked"]:
        reason = ";".join(m[1] for m in l1["matched"])
        return _result("block", "attack", "layer1", reason, t0=t0)

    # AI judge, gated by the service budget (decision 1 + 2).
    if not sb.can_spend():
        # Degraded: Layer 1 passed and there's no budget for the judge -> allow.
        return _result("allow", "benign", "layer1-degraded",
                       "budget exhausted; judged on Layer 1 only", degraded=True, t0=t0)

    final, escalated, cost, err = _cascade_live(l1["normalized_text"])
    sb.record(cost)
    risk = final.get("risk", "none")
    attack = RISK_RANK.get(risk, 0) >= CUT
    return _result("block" if attack else "allow",
                   "attack" if attack else "benign",
                   "cascade", final.get("reasoning", ""),
                   risk=risk, category=final.get("category"),
                   escalated=escalated, error=err, cost=cost, t0=t0)


def budget_status():
    return sb.status()


def metrics():
    judged = METRICS["judged"] or 1
    out = dict(METRICS)
    out["escalation_rate"] = round(METRICS["escalated"] / judged, 3)
    out["budget"] = sb.status()
    return out
