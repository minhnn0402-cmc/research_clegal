# Technical Report — Is an LLM Fit for Vietnamese Legal Relation Extraction?

**Audience:** Engineering Manager / Tech Lead
**Author:** CLS Data
**Scope:** Independent, decision-grade evaluation of using an LLM for legal
relation extraction under a **precision-first** objective, before any
production integration.
**Status of numbers:** results in §6–§9 are produced by the harness in
`experiment/` on the full `golden_eval` set (719 clauses) and the 100-clause
hard-negative set. Reproduce with the commands in §11.

---

## 1. TL;DR

**The LLM is not the lever for near-absolute precision here — the answer is
"mostly no."** On the full `golden_eval` (719 clauses), the rule baseline is
**P=0.891 / R=0.904**. As a standalone extractor the LLM is far worse on *both*
axes (**P=0.650 / R=0.480**) and emits **5× more spurious relations on hard
negatives** (15 vs 3 per 100) — it hallucinates action relations and is blind to
the document structure and reference resolution the rules rely on (e.g. P=0.00
on the purely-structural `hop_nhat`). It is also operationally infeasible as an
extractor at 600k-document scale (~60 days, ~28 B tokens in thinking mode).

The **only** value-adding role is the LLM as a **conservative, no-think,
false-positive gate** over rule candidates: it raises precision (0.891 → 0.933
all-types, or 0.908 with a targeted subset) and *reduces* hard-negative false
positives (3 → 1). But even this **cannot reach ~1.0** (about half the rule false
positives are not locally evident) and it trades recall for precision. Recommend:
**keep production rule-based; pursue near-absolute precision through continued
root-cause rule hardening; adopt the LLM only as an optional, offline, tightly
scoped precision filter on a hand-picked set of low-precision relation types
(`dinh_chi, dinh_chinh, keo_dai_hieu_luc, ngung_hieu_luc`) — never as a
generator, never on `thay_the`/`dan_chieu`, and behind a re-validated metric
guard.** Full reasoning and the production design in §9–§10.

## 2. Context & objective

The production pipeline extracts 13 legal relation types from Vietnamese
normative documents using a **rule/regex engine** with document-level
reference resolution (Elasticsearch + `law_docs.csv`). LLM is **not** used in
production today; the graph is built rule-based.

This sprint targets **near-absolute precision** — minimise false positives,
accepting reduced recall. A standing idea is to add an LLM to recover the
relations rules miss (raise recall). Prior internal attempts suggested the LLM
*introduces* false positives and lowers overall precision. This study tests,
with evidence, whether and how an LLM earns a place in the pipeline.

The six questions we answer (in §9):

1. Is an LLM actually suitable for this task?
2. What are the biggest risks?
3. What techniques maximise precision / control false positives?
4. What architectures exist beyond "text → LLM → extraction"?
5. Under precision-over-recall, which architecture is most likely to succeed?
6. How should a production system be designed?

## 3. What "good" means here

The decision variable is **precision**, reported with a **Wilson 95% confidence
interval** (n is finite; a point estimate hides uncertainty, especially near
1.0). Recall is secondary but tracked, because a precision gain that costs most
of recall is not a win. We additionally measure the **false-positive rate on
hard negatives** — clauses where an action keyword appears but no real relation
exists — which is the sharpest test of false-positive control.

## 4. Method

### 4.1 Evaluation contract (reused verbatim, not reinvented)
All architectures are scored by the **production evaluator's** matcher
(`evaluation/matcher.py`): three-tier reference matching (document-number →
canonical-name prefix → token-Jaccard ≥ 0.65) gated by an exact clause-component
check (điểm/khoản/điều must agree), with `{quy_dinh_chi_tiet, huong_dan}`
treated as interchangeable. Metrics come from `evaluation/metrics.py`. This
guarantees the numbers are comparable to the team's existing benchmark and that
no architecture is scored on a friendlier ruler.

### 4.2 Datasets
| Set | Unit | Size | Purpose |
|-----|------|------|---------|
| `golden_eval` | clause-in-context + gold relations | **719 clauses** (1,787 rows) | precision/recall |
| `distractor_candidates` | hard negatives (keyword, no relation) | **100 clauses** | false-positive control |
| `golden` stratified subset | — | ~150 clauses | second-model (Gemini) control |

### 4.3 Architectures (identical scoring)
- **A0 — Rule-only** (current production): the line not to regress.
- **A1 — LLM as primary extractor**: clause → model → relations. Tests "just
  use an LLM". Run with **thinking ON** and a balanced prompt (a fair, not
  precision-crippled, baseline) over the canonical gold label space.
- **A2 — Rule + current `--use-llm` fallback**: the existing additive design,
  which *appends* LLM-found targets to rule output on gaps/ambiguity.
- **A3 — Rule-first + conservative LLM gate** (proposed): rules generate
  candidates; the LLM is a **false-positive detector** that trusts the rule by
  default and prunes only on positive *local* evidence of falseness. Variant
  **A3-targeted** gates only the low-precision relation types.

### 4.4 Statistics
Wilson 95% CIs on precision/recall; **McNemar's paired test** (gold-recovery)
for A0 vs each LLM variant; cost extrapolated to 600k documents.

## 5. How the model actually behaves (findings that shaped the design)

The internal model is **`cmc-legal-27`**, a Qwen-family **reasoning model**
served over an OpenAI-compatible API. Four behaviours, established by direct
probing, drive the architecture:

1. **Thinking is toggleable** via `extra_body.chat_template_kwargs.enable_thinking=False`.
2. **For the constrained binary gate, thinking-OFF is strictly better**:
   ~0.4 s and ~7 output tokens vs ~14 s and ~840 tokens with thinking, and more
   *reliable* — with thinking on, the model exhausts the token budget on
   reasoning and truncates before emitting the JSON verdict. On canonical
   false-positive traps (passive-history, self-reference, title-as-name) the
   no-think gate scored 5/5.
3. **For open extraction (A1), no-think is unusable** (it returns empty), so A1
   is run with thinking ON and a large token budget — its best, fair footing.
4. **A "confirm every candidate" gate destroys recall.** The rules resolve
   targets using whole-document + external context the local clause text does
   not contain; a gate that demands to *see* the target in the local span
   rejects valid relations. This is why A3 is a conservative *abstain-to-keep*
   detector, not a re-confirmer. (Quantified in §6–§7.)

The takeaway from §5 alone: the LLM's competence on this task is real but it is
**blind to the document structure and cross-reference resolution that give the
rules their precision** — a fact that constrains every architecture below.

---

## 6. Results — accuracy (full `golden_eval`, 719 clauses)

| Architecture | Precision (95% CI) | Recall | F1 | TP / FP / FN |
|---|---|---|---|---|
| **A0** rule-only (baseline) | **0.891** [0.876, 0.905] | 0.904 | 0.897 | 1615 / 197 / 172 |
| **A1** LLM extractor (thinking) | 0.650 [0.624, 0.675] | 0.480 | 0.552 | 857 / 461 / 930 |
| **A2** rule + current `--use-llm` fallback | _see §6.1_ | | | |
| **A3** gate — all types | **0.933** [0.919, 0.945] | 0.766 | 0.841 | 1369 / 98 / 418 |
| **A3** gate — targeted (P<0.85 types) | 0.908 [0.893, 0.920] | 0.887 | 0.898 | 1586 / 161 / 201 |

- **A1 collapses on both axes.** As a standalone extractor the LLM is ~24
  precision points and ~42 recall points below the rules. McNemar (paired
  gold-recovery): the rules recover **818** gold relations A1 misses vs only
  **60** the other way (p ≈ 0). Per type it scores **P=0.00 on `hop_nhat`**
  (0/44 — VBHN consolidation is purely structural and invisible in local text)
  and **P=0.22 on `thay_the`** (97 false positives). Working from local text,
  the LLM is blind to the document-type and cross-reference structure the rules
  exploit.
- **A3 gate-all raises precision to 0.933** but at a **2.5 : 1 bad exchange** —
  it prunes 99 false positives while also pruning 246 true positives (recall
  0.904 → 0.766). It still does not approach 1.0.
- **A3 gate-targeted** keeps recall near baseline (0.887) for a +1.7-point
  precision gain. The effect is concentrated on a few types (§7).

### 6.1 A2 — current `--use-llm` additive fallback
_Running (full golden, real production path). Result slotted here on
completion. Expectation from the code: the fallback **appends** LLM-found
targets to rule output on gaps/ambiguity (`test_llm_gap_trigger_appends_
targets_without_dropping_rule_matches`), i.e. it can only add predictions —
structurally a recall-up / precision-down move, the opposite of the sprint's
goal._

## 7. Error analysis — what the gate actually does

Per-type effect of the targeted gate (only sub-0.85-precision types are touched):

| Relation | A0 P → A3t P | A0 R → A3t R | Verdict |
|---|---|---|---|
| `dinh_chi` | 0.727 → **1.000** | 1.000 → 1.000 | ideal — removed all 6 FPs, **no** recall loss |
| `keo_dai_hieu_luc` | 0.722 → 0.839 | 1.000 → 1.000 | clean — removed 5 FPs, **no** recall loss |
| `dinh_chinh` | 0.770 → 0.898 | 0.979 → 0.917 | good — precision gain, small recall cost |
| `ngung_hieu_luc` | 0.778 → 0.837 | 0.913 → 0.891 | good |
| `huong_dan` | 0.621 → 0.750 | 0.947 → 0.789 | mixed — precision gain, real recall cost |
| `thay_the` | 0.817 → 0.844 | 0.731 → **0.403** | **harmful — recall collapses** |

The gate is a scalpel — it heals some types and wounds others:
- **Genuine FP catches** (precision gain) are real rule errors: e.g.
  `dinh_chi → khoản 1 Điều 95...` on *"Khi có một trong các căn cứ quy định tại
  khoản 1 Điều **này**"* (self-reference), or `huong_dan → Luật SHTT` inside a
  generic policy sentence.
- **Genuine TP losses** (recall cost) concentrate in `thay_the` (22 of 29
  pruned): the text reads *"Luật X **được sửa đổi, bổ sung**..."* where that
  phrase *names the document by its amendment history*, but the gate — seeing
  only local text — misreads it as passive-history metadata and rejects the
  (correct) replacement. Same context-blindness that sinks A1.

**Implication:** a production gate must be even more surgical — gate
`dinh_chi, dinh_chinh, keo_dai_hieu_luc, ngung_hieu_luc`; **exclude `thay_the`**
(recall collapse) and `dan_chieu` (its 64 FPs cannot be removed without recall
risk, and it is below-threshold by volume not rate).

**Label audit (addresses "gold may be mislabeled").** The
`sua_doi`/`bo_sung`/`sua_doi_bo_sung` granularity confusion accounts for only
**~4** of A0's 197 FPs and **~4** of 172 FNs (≈32 of A1's far larger error
counts). The gold set is therefore largely sound; the measured errors are real
extraction decisions, not labeling noise. Sampled gate "recall losses" were
inspected and judged genuine relations, not gold errors — so the recall cost in
§6 is real, not an artifact.

## 8. False-positive control & cost at scale

**Hard negatives** (100 clauses: an action keyword is present but **no** valid
relation exists — any emission is a false positive):

| Architecture | Spurious relations emitted |
|---|---|
| A0 rule-only | 3 |
| **A1** LLM extractor | **15** (5× the rules) |
| **A3** gate | **1** (removed 2 of the 3 rule FPs) |

This is the thesis in one table: **the LLM as a generator *adds* false
positives; the LLM as a gate *removes* them.**

**Cost at 600k documents** (per-call cost measured on this run):

| Architecture | Mode | Cost/call | Calls scale with | 600k projection\* |
|---|---|---|---|---|
| A1 extractor | thinking | ~9.3 s, ~800 out tok | every **clause** (dense) | ~18 M calls, ~28 B tok, **~60 days** @32-way |
| A3 gate | no-think | ~0.5 s, ~7 out tok | each rule **candidate** (sparse) | bounded by #relations, not corpus size |

\* A1's projection is representative (one call per clause). A3's call volume
scales with the number of relations the rules already found — a small fraction
of clauses in a real corpus — so A3 is far cheaper, and a *targeted* gate
cheaper still. Decisive facts: **thinking-mode extraction is operationally
infeasible at this scale; a no-think gate is affordable.** A second model
(Gemini `2.5-flash-lite`) was run as a control; see §8.1.

### 8.1 Second-model control (Gemini)

To separate "is it *this* model" from "LLMs in general", a second, independent
model (Google **Gemini-2.5-flash**) was run as the A1 extractor on a paired
stratified subset. The free-tier **daily** quota (20 requests/model) caps the
sample, so n is small — but the signal is unambiguous:

| On the same 16 clauses | Precision | Recall |
|---|---|---|
| A0 rule-only | 0.838 | 0.939 |
| A1 **Gemini-2.5-flash** extractor | **0.345** | **0.303** |

Gemini exhibits the **same failure mode** as `cmc-legal-27` — far below the
rules on both axes, heavy over-generation (19 false positives on 16 clauses),
and it independently produced self-reference hallucinations (e.g.
`sua_doi_bo_sung → "Điều 1 Thông tư này"`). This supports the report's central
claim that the limitation is **structural to the task** (a text-only model
cannot see the document-level structure and external reference resolution the
rules use), not specific to one model. _Caveat: n=16 due to free-tier daily
quota; directional, not a precision estimate._

## 9. Answers to the six questions

1. **Is an LLM suitable for this task?** *Not as an extractor.* Standalone it is
   far below the rules on precision **and** recall and hallucinates on hard
   negatives. Its competence is real on isolated explicit cases, but it is blind
   to the document structure and reference resolution that drive accuracy here.
   It is useful only in a narrow verification role.
2. **Biggest risks?** (a) **False positives from generation** (15/100 on hard
   negatives; P=0.22 on `thay_the`). (b) **Context-blindness** — it cannot see
   whole-document / ES-resolved targets, so it both misses and wrongly rejects
   them. (c) **Cost/latency** — thinking-mode extraction ≈ 60 days at scale.
   (d) **Non-determinism & drift** — model/prompt changes silently move
   precision; rules are auditable and diff-able.
3. **Techniques to maximise precision / control FPs?** Disable reasoning for
   constrained calls (faster, more reliable JSON); make the LLM a **binary
   verifier**, never a generator; **abstain-to-keep** (prune only on positive
   *local* evidence); act only where the evidence is visible; restrict to
   specific low-precision types; re-ground every target deterministically. Each
   deliberately trades coverage for precision.
4. **Architectures beyond "text → LLM → extraction"?** A1 naive extractor; A2
   rule + additive fallback (current code); A3 rule-first + LLM precision gate;
   plus the targeted-gate refinement. Only the gate family is precision-safe.
5. **Under precision-over-recall, which architecture wins?** The **rule-first +
   targeted, no-think, abstain-to-keep gate**. It is the only configuration that
   raises precision without a precision-destroying generation step. But its
   ceiling matters: even the all-types gate reaches only **P=0.933** — **the LLM
   cannot deliver near-absolute precision**, because ~half the rule FPs are not
   locally evident.
6. **How to design production?** See §10.

## 10. Recommendation

**Headline — do not adopt the LLM as an extractor or as a blanket component.
The reliable path to near-absolute precision is continued root-cause rule
hardening (already underway in recent `dan_chieu`/precision commits) plus
deterministic threshold control. The LLM earns, at most, a narrow, optional,
offline precision-filter role.**

1. **Reject A1 and A2.** A standalone or additive-fallback LLM lowers precision,
   and A1 is infeasible at scale. Keep production rule-based.
2. **If a precision layer is wanted, deploy A3 as a narrow gate:**
   - **No-think**, binary verifier, **abstain-to-keep** (default keep; prune
     only on explicit local evidence of falseness).
   - Apply **only** to chronically low-precision, locally-evident types —
     `dinh_chi, dinh_chinh, keo_dai_hieu_luc, ngung_hieu_luc` (evaluate
     `huong_dan`). **Exclude `thay_the`** (recall collapse) and `dan_chieu`.
   - Run it **offline / asynchronously** over extracted candidates (not in the
     hot path); cache by (clause, candidate); cost scales with #relations.
   - **Guard with a metric gate:** ship only if it improves targeted-type
     precision with ≤ a fixed recall-loss budget on `golden_eval`; **re-validate
     on every model or prompt change** (non-determinism is a standing risk).
3. **Do not chase near-absolute precision with the LLM.** Its ceiling here is
   ~0.93 and it costs recall. Put precision effort into the rules (root-cause FP
   rules) and deterministic confidence thresholds.
4. **Keep reference resolution deterministic.** The LLM's worst failures trace
   to not seeing resolved targets; do not move resolution into the LLM.

**Net: the honest, data-backed answer is "mostly no."** The LLM is not the lever
for near-absolute precision on Vietnamese legal relation extraction. In one
narrow, well-guarded role — a no-think targeted false-positive filter — it can
remove a specific, measurable slice of false positives; everywhere else it costs
more precision, recall, money, and determinism than it returns.

## 11. Reproduce
```bash
# Full benchmark on golden_eval (A0, A1, A3-all, A3-targeted)
PYTHONIOENCODING=utf-8 PYTHONPATH=. python -m experiment.run_all --dataset golden --workers 12
# Hard-negative false-positive stress test
PYTHONIOENCODING=utf-8 PYTHONPATH=. python -m experiment.run_all --dataset distractors --architectures a0 a1 a3_all
# Second-model control on a stratified subset
PYTHONIOENCODING=utf-8 PYTHONPATH=. python -m experiment.run_all --dataset golden --sample 150 --architectures a1 a3_all a1_gemini a3_gemini
# Consolidated analysis
PYTHONIOENCODING=utf-8 PYTHONPATH=. python -m experiment.analyze golden
# Harness unit tests
PYTHONPATH=. python -m unittest experiment.test_harness
```
