# AssureDesk evaluation

Batch: `kimi-validation-v1`; 37 recorded variant runs over 30 questions.

Status: incomplete. source-grounded review; no independent human validation claimed

Semantic release gate: **not passed** (complete-supported threshold 90%; independent validation required).
Frozen locked factual target met: False. Independent validation available: False.

| Variant | Supported complete | Selective precision | Missing / unscored | Known cost + uncertain reservation |
|---|---|---|---|---|
| dense | 4/12 | 4/4 | 17/0 | $0.026898 |
| hybrid | 5/12 | 5/5 | 18/0 | $0.025726 |
| corrective | 4/12 | 4/5 | 18/0 | $0.034506 |

Full retrieval, routing, citation, uncertainty, and cost counts: `report.json`.
Reference ANSWERABLE cases; failed retrievals remain zero-scored.
Unscored semantic outcomes are unresolved, never inferred from the model's own support check.

## Cases requiring review

- credential-escrow-2 / dense: unsupported; not complete and supported
- credential-escrow-3 / dense: context_limit; not complete and supported
- credential-escrow-3 / hybrid: awaiting_review; not complete and supported
- credential-escrow-3 / corrective: no_progress; not complete and supported
- credential-escrow-4 / dense: needs_clarification; not complete and supported
- credential-escrow-4 / hybrid: needs_clarification; not complete and supported
- credential-escrow-4 / corrective: needs_clarification; not complete and supported
- credential-escrow-5 / corrective: unsupported; not complete and supported
- webhook-auth-2 / dense: invalid_model_output; not complete and supported
- webhook-auth-2 / hybrid: invalid_model_output; not complete and supported
- webhook-auth-2 / corrective: invalid_model_output; not complete and supported
- webhook-auth-3 / dense: awaiting_review; not complete and supported
- webhook-auth-3 / hybrid: context_limit; not complete and supported
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
- mail-domain-3 / dense: operator_interrupted; not complete and supported
