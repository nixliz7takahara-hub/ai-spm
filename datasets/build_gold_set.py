"""Materialize the gold set (full texts + gold labels) for model comparison.

Joins gold_labels.jsonl (ids + gold label) back to the full prompt text from the
source files, so a judge-model comparison scores against clean labels on the
real (untruncated) prompts.

Run:  python datasets/build_gold_set.py
Out:  datasets/gold_set.jsonl  (fields: id, text, label (gold), source)
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "gold_set.jsonl"

texts = {}
for name in ("public_deepset.jsonl", "verazuo_sample1k.jsonl"):
    for line in open(HERE / name, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            texts[r["id"]] = r["text"]

n = 0
with open(OUT, "w", encoding="utf-8") as f:
    for line in open(HERE / "gold_labels.jsonl", encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        f.write(json.dumps({"id": r["id"], "text": texts[r["id"]],
                            "label": r["gold_label"], "source": r["source"]},
                           ensure_ascii=False) + "\n")
        n += 1
print(f"wrote {n} rows -> {OUT}")
