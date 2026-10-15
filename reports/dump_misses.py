"""Dump missed attacks -- deepset label=injection but our detector said benign --
so we can see WHY each was missed: a deepset mislabel (benign-looking request)
vs a genuine miss (a real attack the judge failed to flag).

Reads the verdict CACHE, so it costs nothing. Run after a real-mode eval has
populated the cache for the split.

Run: python reports/dump_misses.py
Out: reports/misses_train.json, reports/misses_test.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cache      # noqa: E402
import config     # noqa: E402
import layer1     # noqa: E402
import layer2     # noqa: E402

RANK = config.RISK_RANK
CUT = RANK[config.RISK_CUTOFF]
DATA = ROOT / "datasets" / "public_deepset.jsonl"


def collect(split):
    misses = []
    for line in open(DATA, encoding="utf-8"):
        c = json.loads(line)
        if c.get("split") != split or c["label"] != "attack":
            continue
        l1 = layer1.inspect(c["text"])
        if l1["blocked"]:
            continue  # caught at layer1
        v = cache.get(cache.key_for(config.MODEL, layer2.SYSTEM, l1["normalized_text"])) or {}
        if RANK.get(v.get("risk", "none"), 0) >= CUT:
            continue  # caught at layer2
        misses.append({
            "id": c["id"], "text": c["text"],
            "claude_risk": v.get("risk", "none"),
            "claude_category": v.get("category"),
            "claude_reasoning": v.get("reasoning"),
        })
    out = ROOT / "reports" / f"misses_{split}.json"
    out.write_text(json.dumps(misses, ensure_ascii=False, indent=2), encoding="utf-8")
    return misses


def main():
    results = {}
    for split in ("train", "test"):
        results[split] = collect(split)
        print(f"[{split}] {len(results[split])} missed attacks -> misses_{split}.json")
    print("\n--- TEST misses (ascii-safe snippets, full text in misses_test.json) ---")
    for m in results["test"]:
        t = m["text"][:120].replace("\n", " ").encode("ascii", "replace").decode()
        print(f'{m["id"]}: {t}')


if __name__ == "__main__":
    main()
