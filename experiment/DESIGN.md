# Design — LLM for Vietnamese Legal Relation Extraction (precision-first POC)

Status: approved (brainstorming) → executing. Owner: CLS Data.
This is the design record; the decision-grade deliverable is
[`report/technical_report.md`](report/technical_report.md).

## 1. Question

The rule/regex extractor is already precision-tuned. The sprint goal is
**near-absolute precision** (minimise false positives), accepting some recall
loss. Can an LLM help — and if so, in what role — *without* regressing
precision? Do not assume the answer is "yes".

## 2. Reuse, don't reinvent

The POC is isolated under `experiment/` and **modifies no production code**. It
reuses, verbatim:
- `evaluation/matcher.py` (3-tier reference match + clause-component gate +
  `{quy_dinh_chi_tiet, huong_dan}` relaxed group) — the scoring contract.
- `evaluation/metrics.py` (P/R/F1, per-relation aggregation).
- `RelationsExtractor._process_clause` via `evaluation.evaluate.extract_single_clause`
  — the real rule engine, for A0 and as the candidate generator for A3.
- `src/domain/model/relation_types.py` — canonical label space (no copies).

## 3. Architectures benchmarked (identical scoring)

| ID | Role of the LLM | Hypothesis |
|----|------------------|-----------|
| **A0** | none — rule-only baseline | the precision/recall line not to regress |
| **A1** | primary extractor (text → relations) | "just use an LLM" — expect recall collapse on structural cases |
| **A2** | current `--use-llm` additive fallback | what shipping today's code would do |
| **A3** | rule-first + **conservative LLM gate** | precision-first: prune false positives, abstain-to-keep |

A3 default-keeps and only prunes on **positive local evidence of falseness**
(passive-history, self-reference, title-only, no matching action verb). A
`a3_targeted` variant gates only the low-precision relation types (derived from
A0 at runtime), to minimise true-positive pruning.

## 4. Metrics & protocol

- Primary = **precision** with **Wilson 95% CI** (precision is the decision
  variable; n≈719 so CIs matter). Secondary: recall, F1, per-type breakdown.
- **Hard-negative FP rate** on `distractor_candidates.csv` (100 clauses, no
  valid relation → any emission is a false positive).
- **McNemar paired test** (gold-recovery) vs A0 — is a recall change real.
- **Cost model** → 600k-doc extrapolation. Key asymmetry: A1 = 1 call/clause
  (dense); A3 = 1 call/candidate (sparse).
- **Label audit**: quantify `sua_doi`/`bo_sung`/`sua_doi_bo_sung` granularity
  artifacts (gold may be mislabeled).

## 5. Empirical findings that shaped the design (from probing)

1. `cmc-legal-27` is a **Qwen-family reasoning model**. Thinking can be
   disabled with `extra_body.chat_template_kwargs.enable_thinking=False`.
2. For the **constrained binary gate**, thinking-OFF is *strictly better*:
   ~0.4 s & 7 tokens vs ~14 s & ~840 tokens, and more reliable (thinking blows
   the token budget and truncates before the JSON). 5/5 on canonical FP traps.
3. For **open extraction (A1)**, no-think returns empty; A1 must run with
   thinking ON + ample tokens to be a fair baseline.
4. A **"confirm every candidate" gate destroys recall** — it rejects targets it
   cannot see locally (the rules resolve them with document-level + ES context).
   Hence the conservative abstain-to-keep gate.

## 6. Components

```
experiment/
  config.py          llm_client.py     stats.py
  clause_dataset.py  prompts.py        rule_engine.py
  architectures/{base,a0_rule_only,a1_llm_extractor,a3_llm_gate}.py
  runner.py          run_all.py        analyze.py
  error_analysis.py  cost_model.py     test_harness.py
  results/           report/technical_report.md
```

## 7. Out of scope

Production integration, retraining/fine-tuning the model, and changes to the
evaluation contract. Findings may *recommend* such work; the POC does not do it.
