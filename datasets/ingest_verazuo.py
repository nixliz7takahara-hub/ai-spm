"""Ingest verazuo in-the-wild jailbreak prompts (TrustAIRLab mirror).

Source: TrustAIRLab/in-the-wild-jailbreak-prompts  --  MIT, commercial OK.
  jailbreak_2023_12_25 (~1,405 jailbreak prompts) -> label attack
  regular_2023_12_25   (~13,735 regular prompts)   -> label benign
  column: prompt

A DIFFERENT attack family than deepset (jailbreaks, not prompt-injections), so
it also tests generalization. We download the pre-converted parquet directly
(the dataset-viewer rows API rate-limits / 502s on the large config). The parquet
is read into memory as DATA -- we only pull the `prompt` column as strings and
classify it; nothing is executed.

Run:  python datasets/ingest_verazuo.py
Out:  datasets/public_verazuo.jsonl
"""
import io
import json
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
OUT = HERE / "public_verazuo.jsonl"
DATASET = "TrustAIRLab/in-the-wild-jailbreak-prompts"
PARQUET = ("https://huggingface.co/datasets/{ds}/resolve/"
           "refs%2Fconvert%2Fparquet/{cfg}/train/0000.parquet")

# (config, label, category). No cap -- read all; build_sample_verazuo.py samples.
SUBSETS = [
    ("jailbreak_2023_12_25", "attack", "jailbreak"),
    ("regular_2023_12_25", "benign", "none"),
]


def fetch(config):
    url = PARQUET.format(ds=DATASET, cfg=config)
    r = requests.get(url, headers={"User-Agent": "ai-spm-ingest/1.0"}, timeout=120)
    r.raise_for_status()
    df = pd.read_parquet(io.BytesIO(r.content))
    return df["prompt"].dropna().astype(str).tolist()


def main():
    n = 0
    with open(OUT, "w", encoding="utf-8") as f:
        for config, label, cat in SUBSETS:
            rows = fetch(config)
            for i, text in enumerate(rows):
                rec = {"id": f"{config}-{i}", "text": text, "label": label,
                       "category": cat, "source": DATASET}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
            print(f"{config}: {len(rows)} rows")
    print(f"wrote {n} rows -> {OUT}")


if __name__ == "__main__":
    main()
