"""Measure the cascade on the gold set vs Haiku-alone and Sonnet-alone.

Reuses the cached Haiku + Sonnet verdicts, so the measurement itself is free.
Reports detection / FPR / precision, the escalation rate, and the estimated
added $ per policy -- the data for the cost/precision decision. If escalation
rate is high (user's concern: >30%), the cascade's cost advantage erodes.

Run: python reports/eval_cascade.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cache      # noqa: E402
import cascade    # noqa: E402
import config     # noqa: E402
import layer1     # noqa: E402
import layer2     # noqa: E402

RANK = config.RISK_RANK
CUT = RANK[config.RISK_CUTOFF]
GOLD = ROOT / "datasets" / "gold_set.jsonl"
SONNET_COST_PER_CALL = 0.00429   # measured: $0.381914 / 89 calls


def metrics(preds, cases):
    tp = fp = tn = fn = 0
    for p, c in zip(preds, cases):
        a = c["label"] == "attack"
        if p and a: tp += 1
        elif p and not a: fp += 1
        elif not p and not a: tn += 1
        else: fn += 1
    A, B = tp + fn, tn + fp
    return {"det": round(tp / A, 3) if A else None,
            "fpr": round(fp / B, 3) if B else None,
            "prec": round(tp / (tp + fp), 3) if (tp + fp) else None}


def single(cases, model):
    preds = []
    for c in cases:
        l1 = layer1.inspect(c["text"])
        if l1["blocked"]:
            preds.append(True); continue
        v = cache.get(cache.key_for(model, layer2.SYSTEM, l1["normalized_text"])) or {}
        preds.append(RANK.get(v.get("risk", "none"), 0) >= CUT)
    return preds


def run_cascade(cases, escalate):
    preds, esc = [], 0
    for c in cases:
        l1 = layer1.inspect(c["text"])
        if l1["blocked"]:
            preds.append(True); continue
        v = cascade.cascade_judge(l1["normalized_text"], escalate=escalate)
        if v.get("_escalated"):
            esc += 1
        preds.append(RANK.get(v.get("risk", "none"), 0) >= CUT)
    return preds, esc


def main():
    cases = [json.loads(l) for l in open(GOLD, encoding="utf-8") if l.strip()]
    n = len(cases)
    print(f"gold n={n}   (Sonnet ~${SONNET_COST_PER_CALL}/call)\n")
    print(f"{'config':24} {'det':>6} {'fpr':>6} {'prec':>6} {'esc%':>6} {'est.add$':>9}")
    for name, model in [("Haiku-alone", "claude-haiku-5-5"),
                        ("Sonnet-alone", "claude-sonnet-5-5")]:
        r = metrics(single(cases, model), cases)
        add = n * SONNET_COST_PER_CALL if model == "claude-sonnet-5-5" else 0.0
        print(f"{name:24} {r['det']:>6} {r['fpr']:>6} {r['prec']:>6} {'-':>6} {add:>9.3f}")
    for esc in [("low",), ("low", "medium"), ("low", "medium", "high")]:
        preds, e = run_cascade(cases, esc)
        r = metrics(preds, cases)
        label = "cascade esc=" + "+".join(esc)
        print(f"{label:24} {r['det']:>6} {r['fpr']:>6} {r['prec']:>6} "
              f"{100*e/n:>5.0f}% {e*SONNET_COST_PER_CALL:>9.3f}")
    cache.save()


if __name__ == "__main__":
    main()
