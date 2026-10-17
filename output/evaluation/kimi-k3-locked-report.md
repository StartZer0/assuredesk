# AssureDesk evaluation

Batch: `kimi-locked-v1`; 90 recorded variant runs over 30 questions.

Status: scored. Source-grounded review.

Frozen locked factual target: **met** (complete-supported threshold 90%; corrective result 12/13, or 92.3%).

| Variant | Supported complete | Selective precision | Missing / unscored | Known cost + uncertain reservation |
|---|---|---|---|---|
| dense | 6/13 | 6/8 | 0/0 | $0.429555 |
| hybrid | 10/13 | 10/10 | 0/0 | $0.475764 |
| corrective | 12/13 | 12/13 | 0/0 | $0.653589 |

Full retrieval, routing, citation, uncertainty, and cost counts: `report.json`.
Reference ANSWERABLE cases; failed retrievals remain zero-scored.
Unscored semantic outcomes are unresolved, never inferred from the model's own support check.

## Cases requiring review

- directory-provisioning-1 / dense: awaiting_review; not complete and supported
- directory-provisioning-1 / hybrid: awaiting_review; not complete and supported
- directory-provisioning-2 / dense: awaiting_review; not complete and supported
- directory-provisioning-2 / hybrid: awaiting_review; not complete and supported
- directory-provisioning-3 / dense: awaiting_review; not complete and supported
- directory-provisioning-3 / hybrid: provider_failed; not complete and supported
- directory-provisioning-3 / corrective: awaiting_review; not complete and supported
- directory-provisioning-4 / dense: needs_clarification; not complete and supported
- directory-provisioning-4 / hybrid: needs_clarification; not complete and supported
- directory-provisioning-4 / corrective: needs_clarification; not complete and supported
- artifact-signature-2 / dense: awaiting_review; not complete and supported
- artifact-signature-3 / dense: awaiting_review; not complete and supported
- artifact-signature-3 / hybrid: awaiting_review; not complete and supported
- artifact-signature-3 / corrective: awaiting_review; not complete and supported
- artifact-signature-4 / dense: needs_clarification; not complete and supported
- artifact-signature-4 / hybrid: needs_clarification; not complete and supported
- artifact-signature-4 / corrective: needs_clarification; not complete and supported
- browser-isolation-1 / dense: awaiting_review; not complete and supported
- browser-isolation-2 / dense: awaiting_review; not complete and supported
- browser-isolation-3 / dense: awaiting_review; not complete and supported
- browser-isolation-3 / hybrid: awaiting_review; not complete and supported
- browser-isolation-3 / corrective: awaiting_review; not complete and supported
- browser-isolation-4 / dense: needs_clarification; not complete and supported
- browser-isolation-4 / hybrid: needs_clarification; not complete and supported
- browser-isolation-4 / corrective: needs_clarification; not complete and supported
- build-credential-2 / dense: awaiting_review; not complete and supported
- build-credential-2 / hybrid: awaiting_review; not complete and supported
- build-credential-2 / corrective: awaiting_review; not complete and supported
- build-credential-3 / dense: awaiting_review; not complete and supported
- build-credential-3 / hybrid: awaiting_review; not complete and supported
- build-credential-3 / corrective: awaiting_review; not complete and supported
- build-credential-4 / dense: needs_clarification; not complete and supported
- build-credential-4 / hybrid: needs_clarification; not complete and supported
- build-credential-4 / corrective: needs_clarification; not complete and supported
- object-access-1 / dense: conflict; not complete and supported
- object-access-1 / hybrid: conflict; not complete and supported
- object-access-1 / corrective: conflict; not complete and supported
- object-access-2 / dense: conflict; not complete and supported
- object-access-2 / hybrid: conflict; not complete and supported
- object-access-2 / corrective: conflict; not complete and supported
- object-access-3 / dense: conflict; not complete and supported
- object-access-3 / hybrid: conflict; not complete and supported
- object-access-3 / corrective: conflict; not complete and supported
- object-access-4 / dense: conflict; not complete and supported
- object-access-4 / hybrid: needs_clarification; not complete and supported
- object-access-4 / corrective: needs_clarification; not complete and supported
- object-access-5 / dense: conflict; not complete and supported
- object-access-5 / hybrid: conflict; not complete and supported
- object-access-5 / corrective: conflict; not complete and supported
- regional-agreement-1 / dense: awaiting_review; not complete and supported
- regional-agreement-1 / hybrid: awaiting_review; not complete and supported
- regional-agreement-1 / corrective: awaiting_review; not complete and supported
- regional-agreement-2 / dense: awaiting_review; not complete and supported
- regional-agreement-3 / dense: awaiting_review; not complete and supported
- regional-agreement-3 / hybrid: awaiting_review; not complete and supported
- regional-agreement-3 / corrective: awaiting_review; not complete and supported
- regional-agreement-4 / dense: needs_clarification; not complete and supported
- regional-agreement-4 / hybrid: needs_clarification; not complete and supported
- regional-agreement-4 / corrective: needs_clarification; not complete and supported
- regional-agreement-5 / dense: awaiting_review; not complete and supported
- regional-agreement-5 / hybrid: awaiting_review; not complete and supported
- regional-agreement-5 / corrective: awaiting_review; not complete and supported

## Main metrics

All **30 fresh locked questions × three variants** were run once under `kimi-locked-v1`; all 90 outcomes have source-grounded judgments. Model, prompts, code, corpus and labels remained frozen. All answerable misses and the one hybrid HTTP 429 failure remain counted.

| Metric | Dense | Hybrid | Corrective | Range on this benchmark; ideal |
|---|---|---|---|---|
| Complete supported / 13 answerable | 6/13 (46.2%) | 10/13 (76.9%) | 12/13 (92.3%) | 0–100%; **100%** |
| Selective precision | 6/8 (75.0%) | 10/10 (100%) | 12/13 (92.3%) | 0–100%; **100%** |
| Final candidate Recall@6 | 84.6% | 88.5% | 96.2% | 0–100%; **100%** |
| Final candidate Precision@6 | 28.2% | 29.5% | 32.1% | 0–33.3%; **33.3%** |
| Final candidate MRR@6 | 1.000 | 1.000 | 1.000 | 0–1; **1** |
| Final candidate nDCG@6 | 0.858 | 0.895 | 0.955 | 0–1; **1** |
| Final supplied-context bundle coverage | 20/26 (76.9%) | 23/26 (88.5%) | 25/26 (96.2%) | 0–100%; **100%** |
| Correct routing / 17 non-answerable | 16/17 | 16/17 | 17/17 | 0–100%; **100%** |
| Citation entailment | 14/15 | 20/20 | 25/25 | 0–100%; **100%** |
| Citation coverage | 15/18 | 20/22 | 25/27 | 0–100%; **100%** |
| Unsupported factual assertions | 1/18 | 0/22 | 0/27 | 0–100%; **0%** |
| Processing latency p50 / p95, seconds | 24.1 / 41.8 | 22.3 / 40.5 | 39.6 / 63.5 | ≥0 s; lower is better, no universal maximum |
| Known cost + uncertain reservation | $0.429555 | $0.475764 | $0.653589 | ≥$0; lower is better, no universal maximum |

The range column gives benchmark-specific bounds and the ideal value. Fractions retain observed denominators. Unsupported-assertion rate is best at 0%; cost and latency have no universal maximum.

Ranking metrics average the 13 reference-answerable questions. Precision@6 counts six result positions; this corpus has two reference spans per answerable question, so its achievable maximum is 33.3% (general metric range: 0–100%). Corrective Precision@6 is **32.1% / 33.3% possible**, or 25/78 observed versus 26/78 ideal. MRR of 1.0 indicates that the first relevant span ranks first; it does not establish complete caveat coverage. Processing latency includes provider admission waiting.

Correction recovered **2/3 hybrid misses** and regressed on **0/10 hybrid successes**, an observed +2/13 outcomes. Its descriptive family-bootstrap interval for the paired difference is **0 to +46.2 percentage points** across five answerable families; this small synthetic set does not establish population reliability. Corrective complete-outcome interval: 76.9% to 100%.

The corrective miss omitted the build-credential production-console qualification despite a positive self-check. Dense also omitted a browser-device qualification, added an unsupported deployment restriction to the Nova agreement, and misrouted one ambiguity as conflict. Hybrid's single 429 failure affected a missing-certification case. Every variant's build customer-facing answer added two supported but uncited escrow facts: these reduce citation coverage and need citations or removal before approval. There were no Nova-only chunks in any of the 12 Acme regional-agreement candidate/context traces. No evaluation answer was automatically approved.

The frozen **90% factual target is met** with 12/13 complete supported corrective answers. These results describe a small synthetic benchmark and do not establish production reliability. Reviewer agreement, human review time and benchmark approval-error rates have no observations and are not invented. The project remains a restricted local pilot. [Full metrics](kimi-k3-locked-report.json).

The locked comparison's conservative charge is **$1.558908**, including one **$0.054 unknown reservation**. The reconciled campaign is **$6.635434** ($5.207434 known usage estimate plus $1.428000 uncertain reservations), including all previous provider/model diagnostics, interruptions and failures. The 5 October UTC-day charge is **$1.828908**. The $5/day and $30/campaign caps remain unchanged; these are application estimates, not provider invoices.
