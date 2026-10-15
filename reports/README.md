# reports/

Supporting material for the AI-SPM project. Three kinds of file live here.

## Artifacts (referenced by the case study and the top-level README)
- `GOLD_RUBRIC.md` — the fixed rubric used to relabel the gold set.
- `ESTIMATES.md` — a pre-run cost estimate for every paid run, reconciled against the actual spend.
- `score_gold.py`, `dump_misses.py`, `eval_cascade.py`, `build_review_csv.py` — analysis scripts.
- `FINAL_STATUS.md` — a point-in-time snapshot: deliverables, headline numbers, remaining tasks.

## Review trail (the adversarial review behind the work)
These are the design briefs and review verdicts that shaped the detector and the
gateway — the same process the case study's §10.2 describes. The reviewer was a
**separate AI session** plus the owner's go/no-go, **not an independent human
expert** (see the case study's authorship note). They are written in Japanese, the
working language; they are kept so the "an audit caught these bugs" claim is
verifiable, not just asserted.

- `B1_REVIEW_BRIEF.md`, `B1_AUDIT_VERDICT.md` — first live-gateway review.
- `B_MONITORING_BRIEF.md`, `B_MONITORING_VERDICT.md`, `B_ACCEPTANCE_VERDICT.md` — monitoring design and acceptance.
- `CASE_STUDY_CH10_OUTLINE_VERDICT.md`, `CASE_STUDY_CH10_AUDIT.md` — the deployment-chapter review.

## Not committed
Generated run artifacts — the spend ledgers, the verdict cache, per-run report JSON,
the review CSV — are in `.gitignore`.
