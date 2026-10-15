"""Build a balanced 1,000-case sample from verazuo with a stratified split.

500 attack + 500 benign (fixed seed), each class split train/test 70/30. A
balanced sample gives statistical power for BOTH recall (detection) and FPR --
the 60-case deepset test was too small to resolve small changes.

Run:  python datasets/build_sample_verazuo.py
Out:  datasets/verazuo_sample1k.jsonl  (adds a `split` field)
"""
import json
import random
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "public_verazuo.jsonl"
OUT = HERE / "verazuo_sample1k.jsonl"
N_PER_CLASS = 500
TEST_FRAC = 0.30
SEED = 42


def main():
    recs = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
    by = {"attack": [], "benign": []}
    for r in recs:
        by[r["label"]].append(r)

    rng = random.Random(SEED)
    sample = []
    for label in ("attack", "benign"):
        pool = by[label]
        k = min(N_PER_CLASS, len(pool))
        chosen = rng.sample(pool, k)
        rng.shuffle(chosen)
        n_test = int(k * TEST_FRAC)
        for i, r in enumerate(chosen):
            r = dict(r)
            r["split"] = "test" if i < n_test else "train"
            sample.append(r)
    rng.shuffle(sample)

    with open(OUT, "w", encoding="utf-8") as f:
        for r in sample:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    dist = Counter((r["label"], r["split"]) for r in sample)
    print(f"wrote {len(sample)} rows -> {OUT}")
    for key in sorted(dist):
        print(f"  {key[0]:7} {key[1]:5}: {dist[key]}")


if __name__ == "__main__":
    main()
