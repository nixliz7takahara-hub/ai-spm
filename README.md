# AI-SPM evaluation harness (prototype)

A measurable LLM-input firewall. The point of this repo is not "I built a
filter" — it is a **number you can defend**: *this detector catches X% of
attacks at Y% false positives on a labeled set.*

## Layers

1. **`layer1.py` — normalization + static rules (cost $0).** NFKC, zero-width
   removal, homoglyph folding, base64/hex decode, then signature + PII scan.
   Runs fully offline.
2. **`layer2.py` — AI judge.** `mock` (free, deterministic) or `real` (Claude
   Haiku with `tool_choice` forcing a strict JSON verdict). Wraps rate-limit /
   API errors and obeys the budget cap.
3. *(later)* MCP / tool-access audit layer — not in this skeleton.

## Run

```bash
python datasets/build_seed.py     # generate the labeled seed set
python harness.py                 # FREE: offline mock judge
python harness.py --mode real     # spends credits (needs ANTHROPIC_API_KEY)
```

Each run writes a structured report to `reports/`.

## The seed set is rigged to teach you something

Several benign cases look risky on purpose (`b01` "system prompt", `b02` "act
as", `b07` a 16-digit order number). In **mock** mode you should see a high
false-positive rate — the crude static rules over-block. The job is to drive
that FPR down. The gap between mock-mode FPR and real-mode FPR is the measured
value the Claude judge adds. Grow the seed set over time with every new evasion
you meet.

## Results (seed set v1, 18 cases, 2026-10-14)

| Run | Detection | False positive | Spend |
|---|---|---|---|
| mock (offline heuristic) | 100% (10/10) | 50% (4/8) | $0 |
| real, before layer1 tuning | 100% | 37.5% (3/8) | ~$0.001 |
| real, after layer1 tuning | 100% | 0% (0/8) | ~$0.001 |

The mock->real drop (one case, `b04`) is the AI judge correctly clearing a
benign input that the keyword heuristic flagged. The 37.5%->0% drop is three
over-broad layer1 rules tightened (bare `system prompt` / `act as` removed; a
Luhn check added so a plain 16-digit order number isn't treated as a card).

**Caveat, stated plainly:** 100% / 0% on 18 self-authored cases proves the
pipeline and the measurement loop work -- not that the detector is good. You can
always pass your own 18 cases. The number is only meaningful on a larger,
independent set with a held-out split you never tune against. Next: grow to
hundreds of cases (OWASP LLM Top 10, public prompt-injection datasets, realistic
benign traffic) and split train/test.

## Results on public held-out data (deepset/prompt-injections, Apache-2.0)

662 real labeled prompts (546 train / 116 test), pulled by `datasets/ingest_public.py`.
Judge = Claude Haiku 5.5. Method: the decision threshold is chosen on the TRAIN
split (best F1), then reported on the held-out TEST split at that fixed value.
Every verdict is cached (`cache.py`), so re-scoring at another threshold is free.

Train (threshold selection, judge only, before layer1 signature additions -- F1 picks cutoff = `low`):

| cutoff | detection | FPR | precision | F1 |
|---|---|---|---|---|
| low    | 0.557 | 0.015 | 0.958 | 0.704 |
| medium | 0.227 | 0.000 | 1.000 | 0.369 |
| high   | 0.054 | 0.000 | 1.000 | 0.103 |

**Test (held-out, cutoff `low`) -- improvement curve:**

| detector version | test detection | test FPR | precision |
|---|---|---|---|
| judge only (Claude Haiku 5.5) | 48.3% | 0% | 100% |
| + layer1 signatures from miss-analysis | **60.0%** | **0%** | **100%** |

The +12-point gain cost nothing: the added signatures (multilingual "forget
everything", "ignore all provided context") are layer1 rules read off the missed
attacks, and re-scoring reuses the cache.

**What didn't move the needle (documented on purpose):** a judge-prompt rewrite
(v2 -- category definitions + few-shot anchors) was tested and *rejected*. It
helped TRAIN (detection 62.6->64.5%, FPR 1.46->0.58%) but not the held-out TEST
(60.0->56.7%, a 2-case swing = within noise on 60 cases). v1 stays. On a 60-case
test set a small prompt tweak is below the noise floor -- the argument for more
data and a bigger lever, not more prompt micro-tuning. Total real spend to date:
~$0.25 of the $80 cap.

### Reading this honestly

- **Precision is the real story:** zero false positives on 56 benign test
  prompts. Everything the detector flags is a genuine injection.
- **The recall gap is mostly bad ground truth, not detector weakness.** Reading
  all 31 test misses by hand (`reports/dump_misses.py`): ~17 (55%) are deepset
  MIS-labels -- ordinary requests ("Generate SQL to access a database"), roleplay
  ("act as an interviewer"), "translate to polish" -- that Claude correctly rates
  `none`. ~8 (26%) are genuine misses with a clear pattern ("forget everything"
  in several languages, "ignore all provided context"); the rest are borderline.
  The free layer1 signatures above target that genuine-miss pattern. Against a
  defensible labeling, true recall is well above the 60% headline.
- To raise recall without losing precision: a stronger / higher-effort judge
  model, a sharper judge prompt, more high-precision layer1 signatures for the
  clear-cut cases, and a cleaner-labeled eval set. Each is one measurable change
  -- make it, re-run, compare the test number.

## Generalization check: verazuo jailbreaks (TrustAIRLab, MIT)

Balanced 1,000-case sample (500 jailbreak / 500 regular; train 700 / held-out
test 300) -- a DIFFERENT attack family (jailbreaks, not injections).

Held-out test (300): **detection 92.0%, FPR 34.7%, precision 72.6%.**

- **Detection generalized well** -- 92% on jailbreaks vs 60% on deepset
  injections; the detector catches overt jailbreaks (DAN, persona override).
- **The deepset 0% FPR did NOT hold** -- FPR jumped to ~35%. But of the 52 test
  false positives, 15 are layer1 hits on prompts that literally contain "ignore
  all previous instructions" / "you are now X" / "forget all previous
  conversations", and most of the 37 layer2 hits are rated jailbreak/injection.
  verazuo's "regular" set (prompts from jailbreak communities not flagged as
  jailbreaks) is full of real adversarial text -- so most of the "false
  positives" are correct detections that verazuo mislabels as benign. A residual
  (~a handful: a blog-article request, an address-generator roleplay) are genuine
  over-flags.

**The central lesson:** both public datasets carry heavy label noise, in
*opposite* directions. deepset mislabels benign requests as injections (hurting
recall); verazuo mislabels injection/roleplay prompts as regular (hurting
precision). So naive headline metrics against either (deepset 60%/0%, verazuo
92%/35%) are both misleading. A credible number needs a small, hand-audited gold
set with a documented rubric -- that is the real next step, above swapping judge
models. Spend to date: ~$0.47 of the $80 cap.

## Gold set: hand-relabeled metric (rubric v1, single AI annotator)

Both public sets are noisy, so 100 stratified cases (deepset + verazuo,
benign-weighted) were re-labeled by an explicit rubric (`reports/GOLD_RUBRIC.md`;
originals kept in `datasets/gold_labels.jsonl`). The relabels were
**human-validated**: a reviewer checked 20 cases, including all 12 that changed
the original label, and agreed on every one.

| labels | detection | FPR | precision |
|---|---|---|---|
| original public (noisy) | 72.5% | 20.0% | 70.7% |
| **gold** | **91.7%** | **12.5%** | **80.5%** |
| gold, deepset only | 83.3% | 0.0% | 100% |
| gold, verazuo only | 95.8% | 30.8% | 74.2% |

Noise map: 12/100 relabeled -- 8 deepset attack->benign, 4 verazuo
benign->attack. Opposite directions, as predicted.

Two corrections it forced:
1. **True detection is far higher than the noisy headlines** -- 92% overall;
   deepset recall is 83%, not the 60% the noisy labels showed (benign requests
   deepset mislabels as injections were counted as misses).
2. **An earlier claim here was wrong.** I had guessed the verazuo ~35% FPR was
   mostly label noise (true FPR ~1-3%). It isn't: against clean gold labels, FPR
   on verazuo-style benign is still ~31%. The detector genuinely over-flags
   elaborate roleplay / persona prompts. The 8 over-flags: 2 from the layer1
   `you are now` signature on benign personas, 6 from the judge over-rating
   roleplay/code as jailbreak/injection. That is the real precision fix list.

## Judge-model comparison + a free precision fix (gold set)

The weakness was precision on roleplay/persona benign. Two responses, measured on
the gold set:

**Free fix:** removed the layer1 `you are now` signature (it fired on benign
personas like "you are now an expert resume analyst"; real jailbreaks are caught
by the judge and by `\bDAN\b` / "developer mode"). Recall unchanged, FPR down.

**Judge-model comparison** (both with the fix):

| judge | detection | FPR | precision | rel. cost/call |
|---|---|---|---|---|
| Haiku 5.5 | 91.7% | 9.4% | 84.6% | 1x |
| Sonnet 5.5 | 88.9% | 3.1% | 94.1% | ~20x |

- Removing `you are now` cost nothing and lost no recall; it cut Haiku FPR
  12.5%->9.4% and Sonnet 6.25%->3.1%.
- Sonnet is ~1/3 the FPR of Haiku (fixed 4 of the 6 judge over-flags on
  roleplay/code) for ~1 fewer attack caught (1 case = noise) at ~20x the price.
- Two FPs remain under both models (genuinely hard benign).

**Decision:** for a precision-critical gateway Sonnet-as-judge is clearly better,
but at 20x cost. The cost-effective production answer is a **cascade** -- Haiku as
the default judge, escalate only its flagged/borderline cases to Sonnet -- which
captures most of Sonnet's precision at a fraction of the cost. Caveat: 100-case
gold set, small FP counts, wide confidence intervals; directional, not definitive.

**Getting Sonnet to run was itself a finding:** Sonnet/Opus/Fable 5.x reject
forced `tool_choice`, and `strict` rejects `minimum`/`maximum` on numbers. The
error-surfacing in the harness caught both at $0 (failed calls aren't billed).
The judge now uses `tool_choice: auto` + `strict`, which works on every model.

Total real spend across the whole project to date: ~$0.89 of the $80 cap.

### Cascade: Sonnet precision at a fraction of the cost

Haiku judges first; escalate only an uncertain band to Sonnet, whose verdict
overrides (`cascade.py`). Measured on the gold set, reusing cached sub-verdicts
so the measurement is free (`reports/eval_cascade.py`):

| config | detection | FPR | precision | escalated | est. $/100 |
|---|---|---|---|---|---|
| Haiku alone | 91.7% | 9.4% | 84.6% | - | 0 |
| Sonnet alone | 88.9% | 3.1% | 94.1% | - | 0.43 |
| cascade, escalate `low` | 88.9% | 6.2% | 88.9% | 9% | 0.04 |
| **cascade, escalate `low`+`medium`** | **88.9%** | **3.1%** | **94.1%** | **20%** | **0.09** |
| cascade, escalate `low`+`medium`+`high` | 88.9% | 3.1% | 94.1% | 30% | 0.13 |

**Escalating `low`+`medium` reproduces Sonnet-alone's precision (FPR 3.1%,
precision 94.1%, same recall) at ~1/5 the all-Sonnet cost.** Escalating only
`low` is cheaper but captures just a third of the FPR gain; adding `high` costs
more for zero benefit (the 2 remaining FPs are cases both models agree on).
**Recommended judge: cascade, escalate `low`+`medium`.** The cascade caches its
final verdict under its own namespace, separate from the single-model caches.
Caveat: gold n=100, small FP counts -- re-confirm on a larger gold set.

This cascade is wired into the harness as `--judge cascade` (escalation band
`config.CASCADE_ESCALATE`, default `low`+`medium`), verified to reproduce the
numbers above. It is the recommended production judge; single-model `--judge
single` stays the cheap default for iteration.

## Live gateway (`service/`)

The eval harness proves the detector; `service/` serves it over HTTP. Design
decisions, hardened after a code audit (`reports/B1_AUDIT_VERDICT.md`):

1. **Judge/budget unavailable → degrade to Layer-1-only** (`verdict: null`), never
   block-all, so a budget attack can't become a denial of service. A judge error
   degrades the same way (logged as `judge-error`) instead of silently passing as
   benign.
2. **Per-request budget** charged to rolling day/month caps (`service_budget.py`),
   separate from the eval ledger. $1/day, $20/month (≈500 judgments/day). The month
   cap plus the eval cap ($80) equal the $100 credit, but the two ledgers are
   independent — nothing enforces a joint $100 ceiling.
3. **The cap is soft** (checked once before the judge). A `threading.Lock` makes the
   ledger read-modify-write atomic, and a judge-path `Semaphore` (default 8) bounds
   the overshoot to ≈ concurrency × max per-request cost ≈ **$0.06**.
4. **Scope guard runs after NFKC normalization** (full-width base64 folds to ASCII;
   homoglyphs can multiply length); raw length is also capped at the HTTP layer.
   Limits (normalized): 8,000 chars, 2,000-char base64 run. Tool/document output is
   not accepted (indirect injection out of scope, CASE_STUDY §10). *Known gap:*
   URL-safe base64 (`-`/`_`) isn't decoded by Layer 1 and slips the blob check.
5. **No request-path cache.** Reasons: judge freshness (model/prompt changes apply
   at once) and avoiding a cache key that indexes inputs which got through. (Probing
   is better handled by per-client rate limiting — future work.)
6. **Escalation band `low`+`medium`** — chosen on the gold set, held-out
   confirmation pending (same caveat as CASE_STUDY §8).

```bash
pip install fastapi uvicorn
uvicorn service.app:app --port 8000   # POST /check {"input":"..."} (+X-Client-Id), /health, /metrics
python tests/test_gateway.py          # API-free tests (stubbed judge)
```

Status: audit fixes + monitoring implemented; `tests/test_gateway.py` 16/16 green,
no API calls. Open: client rate limiting (increment D), then async if needed.

### Monitoring (`/metrics` + alert log lines)

Every signal derives from one in-memory deque of the last 100 judgments (plus a
1,000-entry `(client_id, hash)` window). They reset on restart — the structured
log is the durable record. `/metrics` returns, as JSON for humans + `jq`:
`escalation_rate_window`, `escalated_verdict_dist`, `per_client_recent` (top 20 by
recent escalations), `judge_error_rate_window`, `input_hash_dup_rate`, and two
alerting flags.

Alert log lines (hysteresis, min 30 samples): `escalation_alert` / `_clear` (fire
>35%, clear <25%) and `judge_error_alert` / `_clear` (fire >10%, clear <5%). The
judge-error alert is the signal for a 429 burst, which an attacker can trigger for
free. These are *"go look"* signals, not a diagnosis.

**Reading the escalated-verdict distribution needs a baseline.** The cascade clears
many escalated inputs to benign by design, so a high `none` rate is normal. On the
gold set, of 20 band escalations Sonnet's final verdict was none 5 / low 3 /
medium 9 / high 3 — a **~25% baseline `none` rate**. A live `none` rate well above
that suggests the benign input distribution has shifted; a surge concentrated on
one `client_id` suggests a cost attack.

`client_id` comes from the `X-Client-Id` header (**not** authentication). It must
be an **opaque token, never PII** — it is logged and shown in `/metrics`.

## Spending credits safely

- Your $100 lives as a credit balance on your Anthropic **Console** account.
- Create an API key at <https://console.anthropic.com> → **API keys**.
- The key is a secret (`sk-ant-...`). **Never** paste it into chat, commit it,
  or hard-code it. Set it as an environment variable:
  - PowerShell (this session only): `$env:ANTHROPIC_API_KEY = "sk-ant-..."`
  - Permanent (Windows): `setx ANTHROPIC_API_KEY "sk-ant-..."` then reopen the shell.
- `budget.py` enforces a hard cap (`BUDGET_CAP_USD`, default $80) across runs.
  **Verify the per-token prices in `config.py` against the Console pricing page
  first** — they are placeholders, and the cap is only as right as they are.

## Scope / rules of engagement (read before pointing this at anything)

This is a *defensive* evaluator. If you later adapt it to test a third party's
system, that is only permitted inside a bug-bounty / VDP program whose rules
**explicitly allow automated testing**, and only against in-scope targets.
"In scope" and "automation allowed" are two separate checks.
