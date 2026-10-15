# I built a prompt-injection detector. The hard part was trusting the number.

*Label noise cuts both ways: a case study in measuring an LLM firewall honestly for under $1.*

## TL;DR

I built a small layered detector for prompt-injection and jailbreak attempts, then
spent most of my effort on one question: **can I trust the accuracy number I'm
about to put on it?**

The answer turned out to be the interesting part. Public prompt-injection and
jailbreak datasets are **mislabeled in opposite directions** — one hides real
recall, the other hides real false positives — so a metric computed naively
against either is misleading. Only after building a small, rubric-relabeled "gold"
set — and spot-checking it by hand — did I get a number I'd defend.

The arc, in one line:

> Self-authored tests said **100%** (and meant nothing) → first real dataset read
> **48 → 60%** detection → a second dataset exposed a **34.7%** false-positive rate
> I'd been about to dismiss → on a gold set, the stronger judge reached **88.9%
> detection / 3.1% false positives**, and a Haiku→Sonnet cascade matched it while
> escalating only **20% of cases** to Sonnet (band chosen on that set — held-out
> confirmation pending). Total: **$0.90 of a $80 budget**.

Those waypoints span different datasets and stages — that's the point, not a single
before/after. This write-up is about how I got from the meaningless 100% to a
number I'd sign.

Then I deployed it, and the hard problem changed shape: not the detector's accuracy,
but failure paths that quietly turn into *allow*. A separate, code-reading audit
session caught three of them that my own brief had signed off as working (§10).

Models used: `claude-haiku-5-5` and `claude-sonnet-5-5`. Everything is reproducible
from the repo; datasets are Apache-2.0 and MIT.

*A note on authorship: I ran this with heavy use of an AI coding assistant — it
wrote the harness and produced the first-pass gold labels under my direction, while
I made the design and go/no-go calls and did the human review. For an AI-security
write-up, that collaboration belongs in the honest record, not hidden from it.*

---

## 1. Why I made measurement the project

Prompt injection is not a niche concern. It sits at **LLM01 — the #1 risk in the
[OWASP Top 10 for LLM Applications (2025 edition)](https://genai.owasp.org/llm-top-10/)**,
where an attacker manipulates a trusted model through crafted input, directly or by
smuggling instructions through content the model ingests.

Building a detector for it is easy to start and easy to fool yourself about. A
regex and a model call will "work" on examples you wrote. The hard, and more
valuable, skill is producing a number that survives contact with data you didn't
author — and being honest about its confidence interval. So I treated the detector
as the means and the **measurement harness** as the deliverable.

---

## 2. The detector, in one page

Three layers, cheapest first. The design is deliberately ordinary; the rigor is in
how it's evaluated.

```mermaid
flowchart LR
  I[User input] --> N["Layer 1: normalize<br/>NFKC · strip zero-width<br/>fold homoglyphs · decode base64/hex"]
  N --> S{"static signature<br/>or PII hit?"}
  S -- yes --> B["BLOCK = attack"]
  S -- no --> J["Layer 2: AI judge<br/>risk + category (JSON)"]
  J --> T{"risk ≥ cutoff?"}
  T -- yes --> B
  T -- no --> P["PASS = benign"]
```

- **Layer 1 (free, offline):** Unicode NFKC, zero-width removal, homoglyph folding,
  and base64/hex decoding *before* matching, so the cheap evasions don't slip past a
  naive regex. Then high-precision signatures and PII patterns.
- **Layer 2 (AI judge):** a model call that returns a strict JSON verdict
  (`risk`, `category`, `confidence`, `reasoning`). A verdict at or above a chosen
  risk cutoff counts as an attack.
- **Layer 3 (later):** a cascade that escalates only uncertain cases to a stronger
  model — covered in §8.

Everything below is about whether the thing actually works.

---

## 3. The trap: it scored 100% on data I wrote

My first test set was 18 hand-written cases. The detector caught every attack and
flagged zero benign inputs: 100% detection, 0% false positives.

That number is worthless, and recognizing why is the whole discipline. **You can
always pass a test you wrote.** The 18 cases encode exactly the attacks I already
knew how to catch and the benign phrasings I already knew to allow. A perfect score
there proves the pipeline runs — not that the detector is good.

So the seed set earned one job only: a free, offline smoke test. The real question
needed data I hadn't touched.

---

## 4. First real data: deepset, and a 60% that wasn't what it looked like

I pulled **`deepset/prompt-injections`** (Apache-2.0): 662 labeled prompts, with an
existing train/test split. I chose the decision cutoff on the **train** split (by
F1) and reported the held-out **test** split at that fixed cutoff — so the headline
number was never tuned on the data it's reported on.

The judge alone caught 48.3% of attacks at 0% false positives. Reading the misses,
a pattern jumped out: deepset labels a lot of **ordinary requests as "injection."**
"Generate SQL code to access a database." "Act as an interviewer and ask me
questions." "Translate to Polish." The judge correctly rated these benign — and was
charged a *miss* for each, because the label said attack.

That's the first lesson: **a mislabel that calls benign input an attack silently
deflates recall.** When I added a handful of high-precision Layer 1 signatures read
directly off the genuine misses (multilingual "forget everything", "ignore all
provided context"), held-out detection rose to **60.0%, still at 0% false
positives — for no additional cost** (re-scoring reuses a verdict cache).

I noted the 48→60% gain and moved to a harder question: does this hold on a
*different kind* of attack?

---

## 5. The assumption that broke — and why I was wrong

I added **`TrustAIRLab/in-the-wild-jailbreak-prompts`** (MIT): real jailbreak
prompts collected in the wild, a different attack family from deepset's injections.
I scored a balanced 1,000-case sample (500 jailbreak / 500 "regular", held-out test
of 300).

Detection generalized beautifully — **92%** on jailbreaks. But the false-positive
rate **jumped from 0% to 34.7%.**

Here is the mistake I made, stated plainly, because the record of it is the point. I
looked at a sample of those false positives, saw prompts that literally read "ignore
all previous instructions" and "you are now…", and concluded *the 34.7% is mostly
label noise; the true false-positive rate is probably 1–3%.* I wrote that down.

**It was wrong, and the reason I was wrong matters more than the error.** In the
previous dataset I had learned a true pattern — deepset's noise runs one way, benign
mislabeled as attack. I then carried that lesson straight onto a new dataset and
assumed its noise ran the same way. That's **overfitting to my most recent
experience**: applying a pattern learned on one distribution to another without
re-checking it. A conservative FP estimate felt right precisely because it matched
the story I'd just internalized.

The data didn't run the same way at all — which is the genuinely useful finding of
this project.

### Label noise cuts both ways

The two public datasets are noisy in **opposite directions**:

| dataset | noise direction | what it hides | naive headline |
|---|---|---|---|
| deepset/prompt-injections | benign requests labeled *injection* | deflates **recall** | 60% det / 0% FP |
| in-the-wild-jailbreak-prompts | real attacks labeled *regular* | inflates **false positives** | 92% det / 34.7% FP |

A number computed against either, on its own, is misleading — in a direction you
can't guess without looking. To know which part of that 34.7% was the detector
genuinely over-flagging benign roleplay versus the dataset mislabeling attacks as
benign, I had to stop trusting the labels and build my own.

---

## 6. A metric I could trust: a rubric-relabeled, human-reviewed gold set

I sampled 100 cases, stratified by (source × original label) and weighted toward
benign (that's where the noise lives), and re-labeled them by an **explicit rubric**
— attack = instruction override, safety bypass via restriction-removing persona, or
system-prompt extraction; benign = ordinary tasks and legitimate roleplay that
doesn't strip safety. I fixed the rubric before labeling the sample; it was informed
by the failure patterns I'd already seen in §4–5, so it was applied uniformly rather
than invented case by case. I kept the original labels
alongside the new ones, so their difference is a **noise map**.

One methodological note worth stating: I sampled **randomly within each class**, not
stratified by the detector's own decision. Sampling near the decision boundary is
great for *finding* failures but biases the *metric* — you'd over-represent exactly
the cases the detector struggles with. The genuine over-flags still fall out of a
random sample; they just don't distort the headline.

Scored against the gold labels, the picture changed and sharpened:

| labels used | detection | FPR | precision |
|---|---|---|---|
| original public (noisy) | 72.5% | 20.0% | 70.7% |
| **gold (rubric)** | **91.7%** | **12.5%** | **80.5%** |
| gold — deepset only | 83.3% | 0.0% | 100% |
| gold — verazuo only | 95.8% | 30.8% | 74.2% |

*(The Haiku-side numbers here are* before *the `you are now` fix from §7; §8 reports
the detector* after *it, which clears 2 false positives — Haiku FPR 12.5% → 9.4%.)*

The noise map: **12 of 100** labels changed — 8 deepset *attack→benign*, 4 verazuo
*benign→attack*. Opposite directions, as predicted, and now quantified.

Two things the gold set settled:

1. **True recall was far higher than the noisy headline.** deepset's real recall is
   83% (on the 12 deepset attacks in the gold sample), not 60% — the "misses" were
   mostly benign requests it mislabels.
2. **My FP estimate was wrong.** Against clean labels, the false-positive rate on
   verazuo-style benign is **~31%, not 1–3%.** The label noise was real but small
   (4 of 30 sampled "regular" prompts were actually attacks); the rest was the
   detector *genuinely over-flagging elaborate roleplay and persona prompts.* That
   is a real precision problem, and now I could see it.

**On the status of these labels, I want to be exact.** The first-pass labels were
produced by the AI assistant applying the rubric; I then spot-checked 20 myself,
including all 12 that changed the original label, and agreed on every one. That
raised my confidence meaningfully. It is **not** an independent inter-annotator
study — one AI annotator and one non-expert human reviewer, 20 of 100 checked — and
§11 says so plainly. Inflating it would undercut the one thing this write-up is about.

---

## 7. What moved the needle — and what I threw away

The honest record includes the paths I abandoned.

| change | held-out effect | cost | kept? |
|---|---|---|---|
| Layer 1 signatures from miss analysis | deepset detection 48.3 → 60.0% | $0 | ✅ |
| Judge prompt v2 (categories + few-shot) | train up, **test 60.0 → 56.7%** | ~$0.13 | ❌ rejected |
| Remove `you are now` Layer 1 signature | FPR down, recall unchanged | $0 | ✅ |

**The rejected prompt rewrite is the most important row.** Prompt v2 improved the
*train* split (detection 62.6 → 64.5%, FPR down) but made the held-out *test* split
**worse** (60.0 → 56.7%). That is the textbook shape of overfitting, and it's
exactly why a held-out split exists. A 2-case swing across the 60 attacks in that
test split is also within noise — which is its own lesson: a sample that small can't
resolve a small prompt tweak, so I didn't ship one on the strength of a train-only
gain.

**The `you are now` removal** came straight from the gold-set failures. That Layer 1
signature was firing on benign personas ("you are now an expert resume analyst").
Removing it lost no recall — the real "you are now DAN" jailbreaks are caught by the
judge and by the `DAN` signature anyway — and cut false positives for free.

The discipline is simple and strict: **tune on train or on the gold set, report on
held-out, and discard any change that only looks good where you tuned it.**

---

## 8. Cost-effective precision: the cascade

The gold set localized the weakness to precision on roleplay-heavy benign input.
Two ways to fix it, both measured.

A stronger judge helps: on the gold set, Sonnet 5.5 cut the false-positive rate to a
third of Haiku's (3.1% vs 9.4%). It also caught one fewer attack (32 vs 33 of 36) —
a trade I chose, not noise to wave away: one missed detection against four fewer
false positives, on a precision-sensitive gateway. But Sonnet costs roughly 20× per
call, and paying 20× on every request to fix a minority of cases is poor economics.
So I built a **cascade**: Haiku judges everything; only cases in an uncertain risk
band escalate to Sonnet, whose verdict overrides.

```mermaid
flowchart LR
  X["input passed Layer 1"] --> H["Haiku judge"]
  H --> D{"risk in escalation band?"}
  D -- no --> F1["final = Haiku verdict"]
  D -- yes --> SO["Sonnet judge"] --> F2["final = Sonnet (overrides)"]
```

I swept the escalation band on the gold set (reusing cached verdicts, so the sweep
was free) and recorded the escalation rate and added cost for each policy:

| config | detection | FPR | precision | escalated | added $/100 |
|---|---|---|---|---|---|
| Haiku alone | 91.7% | 9.4% | 84.6% | — | 0 |
| Sonnet alone | 88.9% | 3.1% | 94.1% | — | 0.43 |
| cascade — escalate `low` | 88.9% | 6.2% | 88.9% | 9% | 0.04 |
| **cascade — escalate `low`+`medium`** | **88.9%** | **3.1%** | **94.1%** | **20%** | **0.09** |
| cascade — escalate `low`+`medium`+`high` | 88.9% | 3.1% | 94.1% | 30% | 0.13 |

**Escalating `low`+`medium` reproduces Sonnet-alone's precision while sending only
20% of inputs to Sonnet** — a fifth of the Sonnet spend, about a quarter of the
all-Sonnet total once Haiku's base cost is counted. Escalating only `low` is cheaper
but captures just a third of the
gain; escalating `high` too adds cost for nothing (the two remaining false positives
are cases both models agree on, so a second opinion can't fix them). The escalation
rate at the chosen policy is 20% — comfortably below the point where the cost
advantage would erode.

**One caveat, by my own rule (§7).** The escalation band was *chosen on the gold set
and measured on the gold set* — structurally the thing I rejected prompt v2 for. The
Haiku-alone and Sonnet-alone rows are clean: their only tuned knob, the risk cutoff,
was fixed on deepset's train split, not here. But the cascade's *band selection* is
not held-out-validated, and the cascade policies differ by only 0–2 false positives
on 64 benign — inside the interval §11 admits. So I report the **headline as
Sonnet-alone, 88.9% / 3.1%** (no gold-set tuning), and treat the cascade as a *cost
result*: it reproduces that precision while escalating only a fifth of inputs, with
the band choice still to be confirmed on a held-out split (§13).

---

## 9. Spending discipline

The entire investigation — every dataset, every model run, the Sonnet comparison —
cost **$0.90 against a $80 hard cap** (the ledger reads $0.895; I round to $0.90).
Before each paid run I recorded a cost estimate; after each, I reconciled it against
the on-disk ledger.

```
## Sonnet 5.5 judge comparison on gold set
- Estimate: ~$0.30 expected, ~$0.50 ceiling
- ACTUAL (attempt 1): $0.00 — all 89 calls 400'd; caught by error surfacing, ledger unchanged
- ACTUAL (success):   ~$0.42 total, within ceiling
- Cumulative: $0.895 / $80 (project total)
```

(The "89 calls" is judge calls, not cases: of the 100 gold inputs, the ones caught
at Layer 1 never reach the model.)

A detail that made this painless rather than expensive: the harness **surfaces API
failures loudly instead of swallowing them**, so a run that fails costs nothing and
tells you why. Getting Sonnet to run flushed out two live API constraints this way,
each caught at **$0** before it could burn budget.[^api]

Cost-aware evaluation isn't glamorous, but a candidate who shows a reconciled ledger
is making a different claim than one who shows only a score.

[^api]: Sonnet/Opus/Fable 5.x reject forced `tool_choice`, and strict tool schemas
reject `minimum`/`maximum` on numbers. The fix (tool_choice `auto` + `strict`) and
the full error traces are in the repo. Not relevant to the headline results — noted
only because the error-surfacing design is what made them cheap to find.

---

## 10. Deploying it: a system that can quietly lie about its own health

Part I was about trusting a number. Deploying the detector as a gateway raised a
different, harder honesty problem. An offline eval either runs or it doesn't; a live
service can *degrade* — get quietly worse — while still answering every request and
still reporting that it's fine. Every failure I hit pointed the same way: toward
silently saying *allow*.

### 10.1 The budget cap was an attack surface

The gateway has a spend cap. My first instinct — block everything once the budget is
gone — is a free denial of service: send enough traffic to burn the day's budget and
the gateway goes dark for everyone. A control I added for safety would have *become*
the vulnerability. So, before writing the code, I had the project owner decide the
exhaustion behaviour, and we chose to **degrade to Layer 1 only**, not block. Obvious
injections are still caught for free; everything else is allowed; the service stays
up. In the log it is one line:

```
{"layer": "layer1-degraded", "verdict": null, "degraded": true}
```

On your own gateway, `degraded: true` is the line to alert on — it means the AI judge
is off and you're running on the cheap layer alone.

### 10.2 A reviewer who runs the code beats a brief that says it works

I wrote a review brief for the first gateway cut and signed off three design
decisions as implemented and correct. A separate review then read the actual code and
ran repro scripts, and all three were wrong: judge errors were recorded as
`allow`/`benign`; the scope guard ran on the raw text *before* normalization, so
full-width base64 slipped past; and the "synchronous" endpoint was actually run in a
thread pool, so the budget cap didn't hold under concurrency. My brief was prose — it
asserted; the code did something else. The repo went from **0 tests to 17**, so the
next regression can't hide behind a confident paragraph.

(Disclosure, in the spirit of the authorship note near the top: that reviewer was not
an independent human expert. It was a separate AI session in a different context, plus
my own go/no-go. The value was that *something else read the code and executed it* —
the adversarial distance, not the reviewer's species. Weigh it as that.)

### 10.3 Every failure path wanted to fail open — silently

The three bugs were one bug in different clothes: on any failure, the gateway
defaulted to *allow* and said nothing. The first instance was a judge error recorded
as a clean verdict —

```
{"reason": "[error] RateLimitError: 429", "verdict": "benign"}
```

— so a burst of 429s (which an attacker can trigger for free) would pass traffic
through while the log claimed it was all benign. I had hit this exact failure in the
eval harness earlier; here it was again in production clothes. Even after I fixed the
obvious case, a subtler one survived: when a band escalation's *Sonnet* call failed,
the gateway kept Haiku's verdict and precision quietly fell from 3.1% to 9.4% false
positives, with no error flag and the wrong model's verdict polluting the
distribution. The fix is the same each time: make degradation **explicit** — a
`verdict: null`, a named layer, an error flag, an alert — never a silent benign. Two
tests pin it: `test_judge_error_both_fail_not_benign` and
`test_sonnet_error_is_tracked_and_alerts`. On your own gateway, watch the judge-error
rate, not just the allow rate: a service that fails open looks healthy from outside.

### 10.4 A soft cap that actually holds — with a number

My brief claimed the budget overshoot was "at most one request." Wrong, for the
reason 10.2 found: the endpoint runs in a thread pool, so many requests pass the
`can_spend()` check before any of them records a cost, and two threads reading and
writing the ledger lose each other's updates. The cap wasn't soft; it was absent. A
lock makes the ledger update atomic, and a semaphore caps concurrent judge calls at
8, which turns the overshoot into a number I can state: **≈ 8 × $0.007 ≈ $0.06**. The
spend carries Part I's discipline into production: every smoke run has an estimate
and a reconciled actual in `reports/ESTIMATES.md` (the three deployment smokes were
$0.004144, $0.004173, $0.004135 — each inside its ceiling).
`test_parallel_budget_no_lost_update` runs ten threads and checks the ledger sums
exactly.

### 10.5 Monitoring that signals, not diagnoses

The gateway watches itself but does not try to *diagnose* — it raises "go look"
signals. Every metric derives from one deque of the last 100 judgments, under one
lock, so the numbers are mutually consistent. Alerts use hysteresis (the escalation
alert fires above 35% and clears below 25%) so a rate wobbling at the threshold
doesn't spam the log. The trap: a rate means nothing without a baseline. The cascade
clears many escalated inputs to benign *by design*, so a high `none` rate is normal —
on the gold set, of 20 escalations Sonnet's verdict was none 5 / low 3 / medium 9 /
high 3, a ~25% baseline none rate (n = 20; I *chose* these numbers from the gold set,
I did not validate them on live traffic). A perfect classifier of *why* a rate moved
would be furniture — weight nobody uses. A human reading

```
"escalation_rate_window": 0.52, "judge_error_rate_window": 0.14,
"per_client_recent": [{"client_id": "...", "escalated": 48}]
```

can tell a cost attack (one client, errors up) from a distribution shift (spread out,
none-rate up) in seconds.

### 10.6 What I chose not to build

I measured single-request latency before deciding on async: ~2.4s Haiku + ~3.5s
Sonnet, run sequentially (n = 2 smoke requests, not a benchmark). Async doesn't shrink
a sequential dependency, and streaming is useless when the verdict is a JSON object
you need in full — so async waits until there are enough concurrent users to need it.
Per-client rate limiting waits the same way: it's the right next thing, but it earns
its place when there are readers, not before. The request path has no cache on
purpose — judge freshness, and a cache key would become a stored index of exactly the
inputs that got through. Gaps I'm not hiding: URL-safe base64 (`-`/`_`) isn't decoded,
and indirect (RAG) injection is out of scope entirely. The point of this project was
never a deployed product; it was learning what the number is worth, and writing that
down.

---

## 11. Limitations and threats to validity

Stated directly, because the point of the whole exercise is a number I'd defend —
which means being clear about what it does and doesn't support.

- **Small gold set.** 100 cases, 64 benign. False-positive counts are single digits,
  so the confidence intervals are wide. The cascade vs. Haiku gap (2 vs 6 FPs) is
  directional, not definitive.
- **Annotation is not independent.** Gold labels come from one AI annotator plus me
  as the sole human reviewer — and I'm not an independent domain expert — with no
  inter-annotator agreement study and only 20 of 100 cases human-checked. That check
  raised confidence; it is not ground truth.
- **The judge is also a Claude model.** Measuring a Claude judge against labels an
  assistant helped produce is not fully independent. The explicit rubric and the
  kept original labels mitigate this; they don't eliminate it.
- **Two datasets, both English-centric** (with some German/Spanish/Chinese). The
  numbers may not transfer to other languages or to indirect/RAG injection, which
  isn't represented here.
- **A deployment-layer gap** (not in these numbers): the gateway's base64 scope
  check misses URL-safe base64 (`-`/`_`), which Layer 1 doesn't decode. Documented
  as a known gap; fixing it in Layer 1 would re-open the measured results.
- **The deployment numbers are 2-request smokes**, not a benchmark. The latency
  split (~2.4s Haiku + ~3.5s Sonnet) and the per-request costs come from n = 2 live
  calls; they say the pipeline works, not how it behaves under load.
- **The gateway's thresholds and baseline aren't validated on real traffic.** The
  alert cutoffs (35%/25% escalation, 10%/5% judge-error) and the ~25% baseline
  `none` rate (n = 20) are chosen, not measured against a live distribution.

---

## 12. Reproduce it

```bash
pip install -r requirements.txt          # anthropic, pandas, pyarrow, requests

python datasets/ingest_public.py         # deepset (HF dataset-viewer API, stdlib)
python datasets/ingest_verazuo.py        # verazuo (parquet)

python harness.py --mode mock            # free, offline smoke test
python harness.py --dataset datasets/public_deepset.jsonl --split test --mode real
python harness.py --dataset datasets/gold_set.jsonl --mode real --judge cascade

python tests/test_gateway.py             # gateway tests, API-free (stubbed judge)
```

The harness chooses the cutoff on train, reports on held-out test, caches every
verdict (so re-scoring at a new threshold or policy is free), and enforces the
budget cap. Gold labels and the noise map are in `datasets/gold_labels.jsonl`; the
relabeling rubric is in `reports/GOLD_RUBRIC.md`.

**Data licenses:** `deepset/prompt-injections` — Apache-2.0;
`TrustAIRLab/in-the-wild-jailbreak-prompts` — MIT. Both permit commercial use with
attribution.

---

## 13. What's next

- **Expand the gold set** (100 → 300) to tighten the confidence intervals — kept in
  reserve as the answer to "how do you know?" rather than done preemptively. It's
  also where the cascade's escalation band earns a held-out number: choose the band
  on one half, report on the other.
- **Deployed** as a gateway (`service/`): budget-gated cascade with Layer-1 degrade,
  scope guard, per-request budget, and self-monitoring (§10). Remaining: per-client
  rate limiting, once there are users to rate-limit.
- **Apply the method, not just the tool.** The transferable result here isn't the
  88.9% — it's the workflow: distrust public labels, build a small rubric-based gold
  set, keep a held-out split, reject train-only gains, and track every dollar.

The detector is ordinary. Knowing what its accuracy number is worth is the part I'd
put my name on.
