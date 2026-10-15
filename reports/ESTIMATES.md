# Pre-run cost estimates vs actuals

Policy (2026-10-14): record a cost estimate BEFORE each real-mode run, then
reconcile against `budget_ledger.json` AFTER. $80 hard cap is absolute.

## 2026-10-14 - verazuo 1,000-case sample eval (Plan A)
- Dataset: `verazuo_sample1k.jsonl` (1000 = 500 attack / 500 benign; train 700 / test 300)
- Model: `claude-haiku-5-5` ($0.10 / $0.50 per 1M)
- Expected layer2 calls: ~800-900 (some jailbreaks hard-blocked at layer1)
- Note: jailbreak prompts are long, so cost/call is higher than deepset
- **Estimate: ~$0.15 expected, ~$0.35 ceiling**
- Cumulative before run: $0.2527 / $80
- ACTUAL: train $0.15134 + test $0.066849 = **$0.2182** (train 576 + test 249 layer2 calls)
- Cumulative after run: **$0.4709 / $80**
- Reconcile: actual $0.218 landed between my expected ($0.15) and ceiling ($0.35).
  I under-called the expected (jailbreak prompts ran longer than assumed) but
  stayed within the ceiling. Tighten the next estimate for long-text datasets.

## 2026-10-14 - Sonnet 5.5 judge comparison on gold set (Plan B)
- Dataset: `gold_set.jsonl` (100 hand-relabeled; ~89 reach layer2)
- Model: `claude-sonnet-5-5` ($2 / $10 per 1M, ~20x Haiku)
- Purpose: does a stronger judge cut the roleplay over-flagging while keeping recall?
- **Estimate: ~$0.40 expected, ~$0.70 ceiling**
- Cumulative before run: $0.4709 / $80
- ACTUAL (attempt 1): **$0.00** -- all 89 calls 400'd (forced tool_choice is
  rejected on Sonnet 5.5). Caught by the error surfacing, ledger unchanged.
  Fix: tool_choice auto + strict tool. Retry estimate: ~$0.30 exp / ~$0.50 ceiling.
- ACTUAL (attempt 2): schema error -- strict rejects number min/max. $0. Fixed.
- ACTUAL (attempt 3, success): $0.382 full run + $0.023 5-case test + $0.017/$0.001
  re-measures after the you-are-now fix = **~$0.42 total for Plan B**, within ceiling.
- **Cumulative after Plan B: $0.8929 / $80.**

## 2026-10-14 - Cascade measurement (gold set)
- Reused cached Haiku + Sonnet verdicts, so measurement was ~free (~$0.002).
  Cumulative **$0.8951 / $80**.
- Escalation rate + est. added cost per policy (user condition 3):
  esc `low`=9%/$0.04, `low`+`medium`=20%/$0.09, +`high`=30%/$0.13 per 100 cases.
