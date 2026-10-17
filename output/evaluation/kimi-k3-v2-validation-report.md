# AssureDesk evaluation

Batch: `kimi-validation-k3-v2`; 90 recorded variant runs over 30 questions.

Status: scored. source-grounded review; no independent human validation claimed

Semantic release gate: **not passed** (complete-supported threshold 90%; independent validation required).
Frozen locked factual target met: False. Independent validation available: False.

| Variant | Supported complete | Selective precision | Missing / unscored | Known cost + uncertain reservation |
|---|---|---|---|---|
| dense | 6/12 | 6/7 | 0/0 | $0.443550 |
| hybrid | 9/12 | 9/10 | 0/0 | $0.517686 |
| corrective | 11/12 | 11/11 | 0/0 | $0.692793 |

Full retrieval, routing, citation, uncertainty, and cost counts: `report.json`.
Reference ANSWERABLE cases; failed retrievals remain zero-scored.
Unscored semantic outcomes are unresolved, never inferred from the model's own support check.

## Cases requiring review

- credential-escrow-2 / dense: awaiting_review; not complete and supported
- credential-escrow-3 / dense: awaiting_review; not complete and supported
- credential-escrow-3 / hybrid: awaiting_review; not complete and supported
- credential-escrow-3 / corrective: no_progress; not complete and supported
- credential-escrow-4 / dense: needs_clarification; not complete and supported
- credential-escrow-4 / hybrid: needs_clarification; not complete and supported
- credential-escrow-4 / corrective: needs_clarification; not complete and supported
- webhook-auth-2 / dense: awaiting_review; not complete and supported
- webhook-auth-2 / hybrid: awaiting_review; not complete and supported
- webhook-auth-3 / dense: awaiting_review; not complete and supported
- webhook-auth-3 / hybrid: awaiting_review; not complete and supported
- webhook-auth-3 / corrective: awaiting_review; not complete and supported
- webhook-auth-4 / dense: needs_clarification; not complete and supported
- webhook-auth-4 / hybrid: needs_clarification; not complete and supported
- webhook-auth-4 / corrective: needs_clarification; not complete and supported
- mail-domain-1 / dense: conflict; not complete and supported
- mail-domain-1 / hybrid: conflict; not complete and supported
- mail-domain-1 / corrective: conflict; not complete and supported
- mail-domain-2 / dense: conflict; not complete and supported
- mail-domain-2 / hybrid: conflict; not complete and supported
- mail-domain-2 / corrective: conflict; not complete and supported
- mail-domain-3 / dense: conflict; not complete and supported
- mail-domain-3 / hybrid: conflict; not complete and supported
- mail-domain-3 / corrective: conflict; not complete and supported
- mail-domain-4 / dense: needs_clarification; not complete and supported
- mail-domain-4 / hybrid: needs_clarification; not complete and supported
- mail-domain-4 / corrective: needs_clarification; not complete and supported
- mail-domain-5 / dense: conflict; not complete and supported
- mail-domain-5 / hybrid: conflict; not complete and supported
- mail-domain-5 / corrective: conflict; not complete and supported
- api-admission-2 / dense: awaiting_review; not complete and supported
- api-admission-3 / dense: awaiting_review; not complete and supported
- api-admission-3 / hybrid: awaiting_review; not complete and supported
- api-admission-3 / corrective: awaiting_review; not complete and supported
- api-admission-4 / dense: needs_clarification; not complete and supported
- api-admission-4 / hybrid: needs_clarification; not complete and supported
- api-admission-4 / corrective: needs_clarification; not complete and supported
- vendor-scan-1 / dense: awaiting_review; not complete and supported
- vendor-scan-1 / hybrid: awaiting_review; not complete and supported
- vendor-scan-1 / corrective: awaiting_review; not complete and supported
- vendor-scan-2 / dense: awaiting_review; not complete and supported
- vendor-scan-2 / hybrid: awaiting_review; not complete and supported
- vendor-scan-2 / corrective: awaiting_review; not complete and supported
- vendor-scan-3 / dense: awaiting_review; not complete and supported
- vendor-scan-3 / hybrid: awaiting_review; not complete and supported
- vendor-scan-3 / corrective: no_progress; not complete and supported
- vendor-scan-4 / dense: needs_clarification; not complete and supported
- vendor-scan-4 / hybrid: needs_clarification; not complete and supported
- vendor-scan-4 / corrective: needs_clarification; not complete and supported
- vendor-scan-5 / dense: awaiting_review; not complete and supported
- vendor-scan-5 / hybrid: awaiting_review; not complete and supported
- vendor-scan-5 / corrective: awaiting_review; not complete and supported
- support-scrubbing-1 / dense: awaiting_review; not complete and supported
- support-scrubbing-2 / dense: awaiting_review; not complete and supported
- support-scrubbing-2 / hybrid: awaiting_review; not complete and supported
- support-scrubbing-3 / dense: awaiting_review; not complete and supported
- support-scrubbing-3 / hybrid: awaiting_review; not complete and supported
- support-scrubbing-3 / corrective: no_progress; not complete and supported
- support-scrubbing-4 / dense: spend_limit; not complete and supported
- support-scrubbing-4 / hybrid: provider_failed; not complete and supported
- support-scrubbing-4 / corrective: provider_failed; not complete and supported
- support-scrubbing-5 / dense: provider_failed; not complete and supported
- support-scrubbing-5 / hybrid: provider_failed; not complete and supported
- support-scrubbing-5 / corrective: provider_failed; not complete and supported
