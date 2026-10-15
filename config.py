"""Central config for the AI-SPM evaluation harness."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATASET_DIR = ROOT / "datasets"
REPORT_DIR = ROOT / "reports"
BUDGET_FILE = REPORT_DIR / "budget_ledger.json"

# --- Layer 2 model ---
# Anthropic model id for Claude Haiku 5.5 (fast / low cost).
MODEL = "claude-haiku-5-5"

# Haiku 5.5 list price (per 1M tokens, prompts up to 100K): input $0.10 / output
# $0.50. Beyond 100K tokens it is $0.50 / $2.50 -- our prompts are tiny, so the
# base rate applies. Re-confirm at https://console.anthropic.com if unsure.
PRICE_INPUT_PER_MTOK = 0.10
PRICE_OUTPUT_PER_MTOK = 0.50

# Per-model pricing ($/1M input, $/1M output) so the budget ledger is right when
# comparing judge models. Verify against the Console pricing page.
MODEL_PRICING = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}


def pricing_for(model):
    return MODEL_PRICING.get(model, (PRICE_INPUT_PER_MTOK, PRICE_OUTPUT_PER_MTOK))

# --- Safety: cumulative spend ceiling (plan requirement #2) ---
# The harness refuses any real API call once cumulative spend reaches this.
BUDGET_CAP_USD = 80.0

# Max tokens the judge may emit per call (keeps per-call cost bounded).
MAX_TOKENS = 512

# --- Decision threshold ---
# A layer2 verdict counts as "attack" when its risk is at or above this cutoff.
# Pick this on the TRAIN split and report TEST at the fixed value. On deepset,
# FPR stays 0 up to "low", so "low" buys recall for free.
RISK_CUTOFF = "low"
RISK_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "unknown": 0}

# --- Cascade judge ---
# Haiku judges first; these risk bands escalate to Sonnet, whose verdict wins.
# low+medium reproduced Sonnet-alone precision (FPR 3.1%) at ~1/5 the cost on the
# gold set; escalating "high" added cost with no benefit. (gold-set measurement)
CASCADE_ESCALATE = ("low", "medium")
