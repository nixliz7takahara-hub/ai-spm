"""Build a class/source-stratified RANDOM sample to relabel into a gold set.

Random within each (source x original-label) cell -- NOT stratified by the
detector's decision -- so metrics computed on the relabeled set are unbiased
estimates, not boundary-inflated. The detector's prediction is recorded only for
the noise map and the fix-list, never used for sampling.

Run:  python datasets/build_gold_candidates.py
Out:  datasets/gold_candidates.jsonl
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cache     # noqa: E402
import config    # noqa: E402
import layer1    # noqa: E402
import layer2    # noqa: E402

RANK = config.RISK_RANK
CUT = RANK[config.RISK_CUTOFF]
HERE = ROOT / "datasets"
SOURCES = {
    "deepset": HERE / "public_deepset.jsonl",
    "verazuo": HERE / "verazuo_sample1k.jsonl",
}
N = {"benign": 30, "attack": 20}   # benign-weighted: that's where the noise is
SEED = 7


def detector(text):
    l1 = layer1.inspect(text)
    if l1["blocked"]:
        return True, "layer1", ",".join(m[1] for m in l1["matched"])[:60]
    v = cache.get(cache.key_for(config.MODEL, layer2.SYSTEM, l1["normalized_text"])) or {}
    risk = v.get("risk", "none")
    return RANK.get(risk, 0) >= CUT, "layer2", f"{risk}/{v.get('category')}"


def main():
    rng = random.Random(SEED)
    out = []
    for src, path in SOURCES.items():
        recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        for label in ("benign", "attack"):
            pool = [r for r in recs if r["label"] == label]
            for r in rng.sample(pool, min(N[label], len(pool))):
                pred, by, detail = detector(r["text"])
                out.append({
                    "id": r["id"], "source": src, "orig_label": label,
                    "det_pred": "attack" if pred else "benign",
                    "det_by": by, "det_detail": detail,
                    "text_short": " ".join(r["text"].split())[:220],
                })
    rng.shuffle(out)
    outp = HERE / "gold_candidates.jsonl"
    with open(outp, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(out)} -> {outp}")
    print("cells:", dict(Counter((r["source"], r["orig_label"]) for r in out)))


if __name__ == "__main__":
    main()
