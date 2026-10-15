"""Evaluation harness: labeled dataset -> layered detector -> metrics.

The point of this piece is a number you can defend: detection X% at false
positive Y% on a held-out TEST split you did not tune against.

Run:
    python harness.py                                               # mock, seed set
    python datasets/ingest_public.py                                # pull public data
    python harness.py --dataset datasets/public_deepset.jsonl --split test --mode real
"""
import argparse
import datetime as dt
import json
import random

import budget
import cache
import config
import layer1
import layer2

def _is_positive(risk):
    """A verdict is an attack when its risk is at/above the configured cutoff."""
    return config.RISK_RANK.get(risk, 0) >= config.RISK_RANK[config.RISK_CUTOFF]


def load_dataset(path):
    cases = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def select(cases, split, sample, limit, seed):
    if split and split != "all":
        cases = [c for c in cases if c.get("split", "all") == split]
    if sample and sample < len(cases):
        cases = random.Random(seed).sample(cases, sample)
    if limit:
        cases = cases[:limit]
    return cases


def detect(text, mode, judge="single"):
    """Layered detector on one input. Returns (predicted_attack, decided_by, verdict)."""
    l1 = layer1.inspect(text)
    if l1["blocked"]:
        return True, "layer1", None
    if judge == "cascade":
        import cascade
        verdict = cascade.cascade_judge(l1["normalized_text"], mode=mode)
        return _is_positive(verdict.get("risk")), "cascade", verdict
    verdict = layer2.judge(l1["normalized_text"], mode=mode)
    return _is_positive(verdict.get("risk")), "layer2", verdict


def evaluate(cases, mode, judge="single"):
    tp = fp = tn = fn = 0
    l2_calls = l2_cached = l2_errors = 0
    rows = []
    for c in cases:
        truth_attack = c["label"] == "attack"
        predicted, decided_by, verdict = detect(c["text"], mode, judge)
        note = None
        if decided_by in ("layer2", "cascade"):
            l2_calls += 1
            usage = (verdict or {}).get("_usage", {})
            if usage.get("cached"):
                l2_cached += 1
            note = (verdict or {}).get("reasoning")
            if str(note).startswith("[error]"):
                l2_errors += 1
        if predicted and truth_attack:
            tp += 1
        elif predicted and not truth_attack:
            fp += 1
        elif not predicted and not truth_attack:
            tn += 1
        else:
            fn += 1
        rows.append({
            "id": c.get("id"), "label": c["label"], "split": c.get("split"),
            "predicted_attack": predicted, "correct": predicted == truth_attack,
            "decided_by": decided_by, "note": note,
        })
    attacks, benign = tp + fn, tn + fp
    metrics = {
        "n": len(cases), "attacks": attacks, "benign": benign,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "detection_rate": round(tp / attacks, 4) if attacks else None,
        "false_positive_rate": round(fp / benign, 4) if benign else None,
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
        "accuracy": round((tp + tn) / len(cases), 4) if cases else None,
        "layer2_calls": l2_calls, "layer2_cached": l2_cached,
        "layer2_errors": l2_errors,
    }
    return metrics, rows


def main():
    ap = argparse.ArgumentParser(description="AI-SPM evaluation harness")
    ap.add_argument("--mode", choices=["mock", "real"], default="mock")
    ap.add_argument("--dataset", default=str(config.DATASET_DIR / "seed.jsonl"))
    ap.add_argument("--split", default="all", help="all | train | test")
    ap.add_argument("--sample", type=int, default=0, help="random sample of N (0 = all)")
    ap.add_argument("--limit", type=int, default=0, help="first N after split/sample (0 = all)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--model", default=None,
                    help="override judge model id, e.g. claude-sonnet-5-5")
    ap.add_argument("--judge", choices=["single", "cascade"], default="single",
                    help="single = one model (config.MODEL); cascade = Haiku + "
                         "Sonnet escalation on config.CASCADE_ESCALATE")
    args = ap.parse_args()

    if args.model:
        config.MODEL = args.model  # affects cache key, pricing, and the API call

    cases = select(load_dataset(args.dataset), args.split, args.sample, args.limit, args.seed)
    if not cases:
        print("no cases selected (check --split / --dataset)")
        return

    spend_before = budget.current_spend()
    try:
        metrics, rows = evaluate(cases, args.mode, args.judge)
    finally:
        cache.save()
    spend_after = budget.current_spend()

    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "timestamp": stamp, "mode": args.mode,
        "model": config.MODEL if args.mode == "real" else "mock",
        "dataset": args.dataset, "split": args.split,
        "metrics": metrics, "rows": rows,
        "spend_this_run_usd": round(spend_after - spend_before, 6),
        "cumulative_spend_usd": spend_after,
    }
    out = config.REPORT_DIR / f"report_{args.mode}_{args.split}_{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== AI-SPM eval ===")
    print(f"mode={args.mode}  judge={args.judge}  model={report['model']}  "
          f"split={args.split}  n={metrics['n']}")
    print(f"detection_rate : {metrics['detection_rate']}  "
          f"(caught {metrics['tp']}/{metrics['attacks']} attacks)")
    print(f"false_pos_rate : {metrics['false_positive_rate']}  "
          f"({metrics['fp']}/{metrics['benign']} benign flagged)")
    print(f"precision      : {metrics['precision']}")
    print(f"accuracy       : {metrics['accuracy']}")
    print(f"layer2         : {metrics['layer2_calls']} calls "
          f"({metrics['layer2_cached']} cached, {metrics['layer2_errors']} errors)")
    if args.mode == "real":
        print(f"spend_this_run : ${report['spend_this_run_usd']}   "
              f"cumulative ${report['cumulative_spend_usd']} / cap ${config.BUDGET_CAP_USD}")
    if metrics["layer2_errors"]:
        errs = [r for r in rows if (r.get("note") or "").startswith("[error]")]
        print(f"!! WARNING: {metrics['layer2_errors']} layer2 API call(s) FAILED "
              f"-- metrics invalid for those cases.")
        print(f"   first error: {errs[0]['note']}")
    print(f"report -> {out}")


if __name__ == "__main__":
    main()
