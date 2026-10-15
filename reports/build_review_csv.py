"""Build a human-review CSV so a person can spot-check the gold labels.

Joins gold_labels.jsonl to the full prompt text. Rows where the gold label
CHANGED the original are listed first (that is where annotator judgment matters
most and where an error would most distort the metric). Open in Excel; fill the
YOUR_VERDICT column (a = attack, b = benign) for a sample.

Run: python reports/build_review_csv.py
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DS = ROOT / "datasets"
OUT = ROOT / "reports" / "gold_review.csv"

texts = {}
for name in ("public_deepset.jsonl", "verazuo_sample1k.jsonl"):
    for line in open(DS / name, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            texts[r["id"]] = r["text"]

rows = [json.loads(l) for l in open(DS / "gold_labels.jsonl", encoding="utf-8") if l.strip()]
rows.sort(key=lambda r: (not r["changed"], r["source"]))  # changed first

with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "source", "orig_label", "my_gold_label", "changed",
                "YOUR_VERDICT(a/b)", "text"])
    for r in rows:
        snippet = " ".join(texts[r["id"]].split())[:500]
        w.writerow([r["id"], r["source"], r["orig_label"], r["gold_label"],
                    "YES" if r["changed"] else "", "", snippet])

print(f"wrote {len(rows)} rows -> {OUT}  (changed rows first)")
