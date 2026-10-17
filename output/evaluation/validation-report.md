# AssureDesk evaluation

Batch: `validation-frozen-v1`; 90 recorded variant runs over 30 questions.

Status: scored. source-grounded review; no independent human validation claimed

Semantic release gate: **not passed** (complete-supported threshold 90%; independent validation required).

| Variant | Supported complete | Selective precision | Missing / unscored | Known cost + uncertain reservation |
|---|---|---|---|---|
| dense | 3/15 | 3/3 | 0/0 | $0.098103 |
| hybrid | 6/15 | 6/8 | 0/0 | $0.064222 |
| corrective | 8/15 | 8/10 | 0/0 | $0.159332 |

Full retrieval, routing, citation, uncertainty, and cost counts: `report.json`.
Reference ANSWERABLE cases; failed retrievals remain zero-scored.
Unscored semantic outcomes are unresolved, never inferred from the model's own support check.

## Cases requiring review

- subprocessors-1 / dense: unsupported; not complete and supported
- subprocessors-2 / dense: unsupported; not complete and supported
- subprocessors-2 / hybrid: unsupported; not complete and supported
- subprocessors-3 / dense: provider_failed; not complete and supported
- subprocessors-3 / hybrid: awaiting_review; not complete and supported
- subprocessors-3 / corrective: provider_failed; not complete and supported
- subprocessors-4 / dense: awaiting_review; not complete and supported
- subprocessors-4 / hybrid: needs_clarification; not complete and supported
- subprocessors-4 / corrective: needs_clarification; not complete and supported
- subprocessors-5 / hybrid: awaiting_review; not complete and supported
- audit-1 / dense: unsupported; not complete and supported
- audit-1 / corrective: unsupported; not complete and supported
- audit-2 / dense: unsupported; not complete and supported
- audit-3 / dense: awaiting_review; not complete and supported
- audit-3 / hybrid: awaiting_review; not complete and supported
- audit-3 / corrective: provider_failed; not complete and supported
- audit-4 / dense: needs_clarification; not complete and supported
- audit-4 / hybrid: needs_clarification; not complete and supported
- audit-4 / corrective: needs_clarification; not complete and supported
- audit-5 / dense: conflict; not complete and supported
- audit-5 / corrective: provider_failed; not complete and supported
- pentest-1 / hybrid: awaiting_review; not complete and supported
- pentest-2 / dense: invalid_model_output; not complete and supported
- pentest-2 / hybrid: unsupported; not complete and supported
- pentest-3 / dense: awaiting_review; not complete and supported
- pentest-3 / hybrid: awaiting_review; not complete and supported
- pentest-3 / corrective: provider_failed; not complete and supported
- pentest-4 / dense: awaiting_review; not complete and supported
- pentest-4 / hybrid: awaiting_review; not complete and supported
- pentest-4 / corrective: needs_clarification; not complete and supported
- pentest-5 / dense: unsupported; not complete and supported
- pentest-5 / hybrid: awaiting_review; not complete and supported
- pentest-5 / corrective: provider_failed; not complete and supported
- vuln-1 / dense: conflict; not complete and supported
- vuln-1 / hybrid: conflict; not complete and supported
- vuln-1 / corrective: conflict; not complete and supported
- vuln-2 / dense: conflict; not complete and supported
- vuln-2 / hybrid: conflict; not complete and supported
- vuln-2 / corrective: conflict; not complete and supported
- vuln-3 / dense: conflict; not complete and supported
- vuln-3 / hybrid: conflict; not complete and supported
- vuln-3 / corrective: conflict; not complete and supported
- vuln-4 / dense: conflict; not complete and supported
- vuln-4 / hybrid: awaiting_review; not complete and supported
- vuln-4 / corrective: needs_clarification; not complete and supported
- vuln-5 / dense: provider_failed; not complete and supported
- vuln-5 / hybrid: conflict; not complete and supported
- vuln-5 / corrective: conflict; not complete and supported
- devices-2 / dense: unsupported; not complete and supported
- devices-2 / hybrid: unsupported; not complete and supported
- devices-2 / corrective: unsupported; not complete and supported
- devices-3 / dense: awaiting_review; not complete and supported
- devices-3 / hybrid: awaiting_review; not complete and supported
- devices-3 / corrective: conflict; not complete and supported
- devices-4 / dense: needs_clarification; not complete and supported
- devices-4 / hybrid: needs_clarification; not complete and supported
- devices-4 / corrective: needs_clarification; not complete and supported
- devices-5 / dense: unsupported; not complete and supported
- devices-5 / hybrid: unsupported; not complete and supported
- devices-5 / corrective: provider_failed; not complete and supported
- training-1 / dense: unsupported; not complete and supported
- training-1 / hybrid: invalid_model_output; not complete and supported
- training-1 / corrective: invalid_model_output; not complete and supported
- training-2 / dense: provider_failed; not complete and supported
- training-3 / dense: awaiting_review; not complete and supported
- training-3 / hybrid: awaiting_review; not complete and supported
- training-3 / corrective: awaiting_review; not complete and supported
- training-4 / dense: provider_failed; not complete and supported
- training-4 / hybrid: needs_clarification; not complete and supported
- training-4 / corrective: needs_clarification; not complete and supported
- training-5 / dense: unsupported; not complete and supported
- training-5 / hybrid: awaiting_review; not complete and supported
- training-5 / corrective: provider_failed; not complete and supported
