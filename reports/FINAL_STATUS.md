# AI-SPM project — final status

Facts only. Whether to publish is the owner's call; no recommendation is given here.

Last commit at writing: `e4c5ae9` (§10 resubmission). Date: 2026-10-15.

---

## 1. Headline numbers

| metric | value | basis |
|---|---|---|
| Detection (recall) | **88.9%** | held-out gold set, n=100 (36 attacks) |
| False-positive rate | **3.1%** | same (64 benign) |
| Precision | **94.1%** | same |
| Escalation to Sonnet | **~20%** | cascade on the gold set |
| Cascade cost vs all-Sonnet | **~1/5** | escalates only the low+medium band |
| Total real spend | **~$0.91 / $80 cap** | eval ledger $0.895 + service ledger $0.0125 (two independent ledgers) |

Caveat carried in the write-up: these are on a 100-case single-annotator gold set;
the escalation band was chosen on that set (held-out confirmation pending). The
deployment numbers (latency, per-request cost) are 2-request smokes, not a benchmark.

## 2. Deliverables (one line each)

**Writing**
- `CASE_STUDY.md` — the case study: honest measurement under label noise (§1–§9) +
  deployment lessons (§10) + limitations/reproduce/next (§11–§13).
- `README.md` — repo guide, results tables, gateway + monitoring docs.

**Detector**
- `layer1.py` — normalization (NFKC, zero-width, homoglyph, base64/hex) + static signatures + PII.
- `layer2.py` — AI judge (strict JSON verdict), mock + real, module client.
- `cascade.py` — Haiku→Sonnet cascade (escalate low+medium).
- `config.py` — model ids, pricing, cutoff, escalation band.

**Evaluation harness**
- `harness.py` — dataset → layered detector → metrics; train/test split, verdict cache, budget cap.
- `budget.py` — eval cost ledger + hard cap. `cache.py` — verdict cache.

**Datasets & gold set**
- `datasets/ingest_public.py` (deepset, Apache-2.0), `ingest_verazuo.py` (verazuo, MIT), `build_*.py`.
- `datasets/gold_labels.jsonl` — human-reviewed gold labels (id→label, no prompt text).
- `reports/GOLD_RUBRIC.md` — the fixed relabeling rubric. `score_gold.py` / `dump_misses.py` / `eval_cascade.py` — analysis.

**Service (gateway)**
- `service/gateway.py` — budget-gated cascade, Layer-1 degrade, scope guard, monitoring.
- `service/service_budget.py` — day/month caps (locked). `service/app.py` — FastAPI layer.

**Tests & ledger**
- `tests/test_gateway.py` — 17 API-free tests (17/17 green).
- `reports/ESTIMATES.md` — pre-run estimates reconciled against actuals.

**Audit trail** (review/verdict docs)
- `reports/B1_REVIEW_BRIEF.md`, `B1_AUDIT_VERDICT.md`, `B_MONITORING_BRIEF.md`,
  `B_MONITORING_VERDICT.md`, `B_ACCEPTANCE_VERDICT.md`, `CASE_STUDY_CH10_OUTLINE_VERDICT.md`,
  `CASE_STUDY_CH10_AUDIT.md`.

## 3. Remaining tasks and their trigger conditions

| task | trigger condition (when to start) |
|---|---|
| Expand gold set 100 → 300 | When the 88.9%/3.1% is challenged as under-powered, or before citing it as more than directional. Also supplies the held-out confirmation of the cascade band (pick on one half, report on the other). |
| Increment D: per-client rate limiting | When the gateway serves real multi-client traffic (there are users to rate-limit). `X-Client-Id` and per-client monitoring are already in place as the prerequisite. |
| URL-safe base64 decode in Layer 1 | Only bundled with a gold-set re-run: changing Layer 1 re-opens the measured numbers, so it is not a standalone fix. |

## 4. Work needed before publishing (facts; verified items marked ✓)

- **Secret scan ✓** — no real API key is tracked. The 6 `sk-ant` matches are README
  placeholders (`sk-ant-...`), one fake test key in `build_seed.py` / `seed.jsonl`
  (the PII-leak test case `a10`), and the detection regex in `layer1.py`.
- **Budget logs / generated data ✓** — not tracked. `budget_ledger.json`,
  `verdict_cache.json`, `service/budget_state.json`, `reports/report_*.json`,
  `gold_review.csv`, `misses_*.json`, `.env`, and the downloaded datasets are all in
  `.gitignore`. 36 files are tracked: source, docs, scripts, `gold_labels.jsonl`, `seed.jsonl`.
- **Repo license ✓** — `LICENSE` (MIT) added at repo root; **fill in the copyright
  holder** (currently a placeholder). Dataset licenses (deepset Apache-2.0, verazuo
  MIT) are cited in README/CASE_STUDY and the LICENSE data note; datasets are not
  redistributed.
- **README top ✓** — added a TL;DR with the headline numbers and a prominent link to
  `CASE_STUDY.md`.
- **Audit-trail docs** — kept, with an English index (`reports/README.md`) that
  explains they are the review trail (Japanese working language; reviewer = a separate
  AI session + owner go/no-go). Remove them if a public repo should omit internal
  review; one `git rm` does it.
- **Line endings** — git reports CRLF normalization warnings on commit (Windows). A
  `.gitattributes` with `* text=auto` would standardize this; cosmetic only.
