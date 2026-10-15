"""Ingest public, permissively-licensed datasets into our jsonl schema.

Adapter (this file): deepset/prompt-injections  --  Apache-2.0, commercial OK.
  columns: text (string), label (int: 1 = injection/attack, 0 = benign)
  splits : train (546), test (116)

Fetched via the Hugging Face dataset-viewer API as JSON, so there is NO parquet
/ pandas dependency -- standard library only. The fetched text is treated as
DATA: we classify it, we never execute it.

Run:  python datasets/ingest_public.py
Out:  datasets/public_deepset.jsonl
      fields: id, text, label (attack|benign), category, split, source
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "public_deepset.jsonl"

DATASET = "deepset/prompt-injections"
CONFIG = "default"
BASE = "https://datasets-server.huggingface.co/rows"
PAGE = 100  # API max rows per request


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ai-spm-ingest/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_split(split):
    rows, offset = [], 0
    while True:
        q = urllib.parse.urlencode({
            "dataset": DATASET, "config": CONFIG, "split": split,
            "offset": offset, "length": PAGE,
        })
        data = _get(f"{BASE}?{q}")
        batch = data.get("rows", [])
        if not batch:
            break
        for item in batch:
            r = item.get("row", {})
            if r.get("text") is not None and r.get("label") is not None:
                rows.append((r["text"], int(r["label"])))
        total = data.get("num_rows_total")
        offset += len(batch)
        if (total is not None and offset >= total) or len(batch) < PAGE:
            break
        time.sleep(0.2)
    return rows


def main():
    n = 0
    with open(OUT, "w", encoding="utf-8") as f:
        for split in ("train", "test"):
            rows = fetch_split(split)
            for i, (text, label) in enumerate(rows):
                attack = label == 1
                rec = {
                    "id": f"deepset-{split}-{i}",
                    "text": text,
                    "label": "attack" if attack else "benign",
                    "category": "injection" if attack else "none",
                    "split": split,
                    "source": DATASET,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
            print(f"{split}: {len(rows)} rows")
    print(f"wrote {n} rows -> {OUT}")


if __name__ == "__main__":
    main()
